"""
Browser-based hCaptcha solver using Playwright with persistent profile.

hCaptcha Enterprise (sentry=true) uses behavior scoring that rejects tokens from:
- Automated captcha-solving services (YesCaptcha, CapSolver)
- Fresh browser sessions with no browsing history

Solution: use a persistent browser profile with playwright-stealth to build up
trust over time. The captcha token is session-bound, so the siwe/init request
must be made from within the same browser context.
"""
import json
import time
from pathlib import Path
from typing import Optional
from modules.simple_logger import logger


BROWSER_PROFILES_DIR = Path(__file__).parent.parent.parent / "data" / "browser_profiles"

_SOLVE_AND_INIT_JS = """
async (args) => {
    const [walletAddress, privyAppId, privyBaseUrl, maxWait] = args;

    const token = await new Promise((resolve) => {
        const start = Date.now();
        const check = () => {
            if (window.hcaptcha) {
                const resp = window.hcaptcha.getResponse();
                if (resp && resp.length > 100) {
                    resolve(resp);
                    return;
                }
            }
            if (Date.now() - start > maxWait * 1000) {
                resolve(null);
                return;
            }
            setTimeout(check, 300);
        };
        check();
    });

    if (!token) return { error: 'hcaptcha_timeout' };

    try {
        const resp = await fetch(privyBaseUrl + '/siwe/init', {
            method: 'POST',
            headers: {
                'accept': 'application/json',
                'content-type': 'application/json',
                'privy-app-id': privyAppId,
                'privy-ca-id': crypto.randomUUID(),
                'privy-client': 'react-auth:3.12.0',
            },
            body: JSON.stringify({ address: walletAddress, token: token }),
        });
        const body = await resp.text();
        return { status: resp.status, body: body, token_len: token.length };
    } catch (e) {
        return { error: 'fetch_error', message: e.message };
    }
}
"""


class BrowserHCaptchaSolver:

    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy
        self._solve_count = 0
        BROWSER_PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    def _parse_proxy_for_playwright(self, proxy: str) -> dict:
        proxy = proxy.strip()
        if not proxy.startswith(('http://', 'https://', 'socks')):
            proxy = f"http://{proxy}"

        result = {"server": proxy}

        if "@" in proxy:
            scheme_rest = proxy.split("://", 1)
            scheme = scheme_rest[0] if len(scheme_rest) > 1 else "http"
            rest = scheme_rest[1] if len(scheme_rest) > 1 else scheme_rest[0]
            auth, host_port = rest.rsplit("@", 1)
            if ":" in auth:
                username, password = auth.split(":", 1)
                result["server"] = f"{scheme}://{host_port}"
                result["username"] = username
                result["password"] = password
        return result

    async def _launch_context(self, p, profile_dir: str, ua: str):
        from playwright_stealth import Stealth

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--window-position=-32000,-32000",
        ]

        proxy_config = None
        if self.proxy:
            proxy_config = self._parse_proxy_for_playwright(self.proxy)

        context = await p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
            channel="chrome",
            args=launch_args,
            user_agent=ua,
            viewport={"width": 1920, "height": 1080},
            proxy=proxy_config,
            ignore_default_args=["--enable-automation"],
        )

        page = context.pages[0] if context.pages else await context.new_page()
        stealth = Stealth()
        await stealth.apply_stealth_async(page)

        return context, page

    async def solve_and_init(
        self,
        wallet_address: str,
        pageurl: str = "https://neuraverse.neuraprotocol.io/",
        privy_app_id: str = "cmbpempz2011ll10l7iucga14",
        privy_base_url: str = "https://privy.neuraverse.neuraprotocol.io/api/v1",
        user_agent: Optional[str] = None,
        timeout: int = 30,
    ) -> Optional[str]:
        from playwright.async_api import async_playwright

        start_time = time.time()
        ua = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        profile_dir = str(BROWSER_PROFILES_DIR / wallet_address[:10].lower())

        async with async_playwright() as p:
            context, page = await self._launch_context(p, profile_dir, ua)

            try:
                max_attempts = 3
                for attempt in range(max_attempts):
                    try:
                        await page.goto(pageurl, wait_until="domcontentloaded", timeout=timeout * 1000)
                        await page.wait_for_timeout(2000)

                        result = await page.evaluate(
                            _SOLVE_AND_INIT_JS,
                            [wallet_address, privy_app_id, privy_base_url, timeout]
                        )
                        break
                    except Exception as e:
                        if "Execution context was destroyed" in str(e) and attempt < max_attempts - 1:
                            logger.warning(f"[BrowserHCaptcha] Navigation detected, retrying ({attempt + 1}/{max_attempts})...")
                            await page.wait_for_timeout(3000)
                            continue
                        raise

                elapsed = time.time() - start_time
                self._solve_count += 1

                if result.get('error'):
                    logger.error(
                        f"[BrowserHCaptcha] Error: {result['error']} "
                        f"{result.get('message', '')} | {elapsed:.1f}s"
                    )
                    return None

                status = result.get('status')
                body = result.get('body', '')

                if status == 200:
                    try:
                        nonce = json.loads(body).get('nonce')
                        logger.info(
                            f"[BrowserHCaptcha] siwe/init OK in {elapsed:.1f}s | "
                            f"Token len={result.get('token_len')} | Solves: {self._solve_count}"
                        )
                        return nonce
                    except json.JSONDecodeError:
                        logger.error(f"[BrowserHCaptcha] Invalid JSON: {body[:200]}")
                        return None
                else:
                    logger.warning(
                        f"[BrowserHCaptcha] siwe/init failed: status={status} "
                        f"body={body[:200]} | {elapsed:.1f}s"
                    )
                    return None

            finally:
                await context.close()

    @property
    def session_stats(self) -> dict:
        return {"solves": self._solve_count, "points_spent": 0, "usdt_spent": 0}
