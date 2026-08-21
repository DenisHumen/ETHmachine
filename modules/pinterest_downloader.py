"""
Pinterest Random Image Downloader
Скачивает рандомные картинки из Pinterest через авторизованную сессию
или через гостевой доступ с правильной эмуляцией браузера.
"""
import os
import re
import json
import time
import uuid
import zipfile
import random
import requests
from typing import Optional, List, Tuple

from rich.progress import (
    Progress, BarColumn, TextColumn, DownloadColumn,
    TransferSpeedColumn, TimeRemainingColumn, SpinnerColumn,
)
from rich.console import Console

from modules.simple_logger import log_simple, log_task
from modules.proxy_manager import ProxyManager, parse_proxy
# config/modules/cfg_pinterest.py содержит учётные данные, поэтому лежит
# в .gitignore и создаётся при первом запуске main.py. В свежем клоне его
# ещё нет — берём значения по умолчанию, чтобы модуль импортировался.
try:
    from config.modules.cfg_pinterest import (
        PINTEREST_DOWNLOAD_DELAY, PINTEREST_EMAIL, PINTEREST_IMAGE_QUALITY,
        PINTEREST_MAX_IMAGES, PINTEREST_PASSWORD, PINTEREST_SEARCH_QUERIES,
    )
except ImportError:
    PINTEREST_EMAIL = ''
    PINTEREST_PASSWORD = ''
    PINTEREST_MAX_IMAGES = 500
    PINTEREST_DOWNLOAD_DELAY = [0.2, 0.6]
    PINTEREST_IMAGE_QUALITY = 'originals'
    PINTEREST_SEARCH_QUERIES: list = []

console = Console()

SEARCH_QUERIES = [
    # ── Original 31 ──
    "aesthetic wallpaper", "nature photography", "abstract art",
    "digital art", "landscape", "minimal design", "neon lights",
    "space galaxy", "ocean waves", "mountain view", "sunset sky",
    "flowers macro", "urban photography", "street art", "cyberpunk",
    "anime art", "retro vintage", "watercolor painting", "forest",
    "animals wildlife", "architecture modern", "car photography",
    "food photography", "travel world", "portrait photography",
    "geometric patterns", "fantasy art", "dark aesthetic",
    "pastel colors", "graffiti art", "underwater photography",
    # ── Nature & Landscapes ──
    "tropical beach", "autumn leaves", "cherry blossom", "northern lights aurora",
    "desert dunes", "volcanic landscape", "rainforest canopy", "coral reef",
    "frozen lake", "misty mountains", "lavender field", "tulip garden",
    "bamboo forest", "redwood trees", "savanna sunset", "alpine meadow",
    "fjord norway", "rice terraces", "canyon landscape", "glacier ice",
    "waterfall paradise", "lake reflection", "spring flowers field", "snowy forest",
    "tropical jungle", "rock formation", "cave photography", "river valley",
    "coastal cliffs", "prairie grassland", "mangrove forest", "hot spring",
    "sand dunes pattern", "mossy rocks", "pine forest winter", "wildflower meadow",
    "rainbow sky", "storm clouds", "foggy morning", "starry night sky",
    "milky way photography", "moonrise", "golden hour light", "blue hour city",
    "double rainbow", "lightning storm", "tornado photography", "snow blizzard",
    "ice crystal macro", "frost pattern", "dew drops leaf", "rain drops window",
    "sun rays forest", "cloud formation", "aerial landscape", "drone nature",
    # ── Animals & Wildlife ──
    "wild horses", "eagle flight", "wolf pack", "lion portrait",
    "tiger close up", "elephant family", "giraffe savanna", "zebra pattern",
    "penguin colony", "polar bear arctic", "dolphin jumping", "whale ocean",
    "sea turtle underwater", "jellyfish glow", "butterfly wings macro",
    "dragonfly close up", "hummingbird flower", "owl portrait", "peacock feathers",
    "flamingo pink", "parrot colorful", "fox red forest", "deer forest",
    "bear fishing", "cheetah running", "leopard tree", "gorilla portrait",
    "panda bamboo", "koala tree", "chameleon colors", "frog macro",
    "snake pattern", "octopus underwater", "starfish beach", "seahorse macro",
    "ladybug macro", "bee flower macro", "spider web dew", "cat portrait cute",
    "dog photography", "kitten playing", "puppy cute", "bunny rabbit",
    "hamster cute", "bird nest", "swan lake", "crane flying",
    "fish aquarium", "coral fish tropical", "manta ray", "shark underwater",
    # ── Architecture & Cities ──
    "skyscraper modern", "gothic cathedral", "ancient ruins", "japanese temple",
    "mosque architecture", "bridge photography", "lighthouse coast", "castle medieval",
    "palace interior", "museum modern", "library beautiful", "staircase spiral",
    "window architecture", "door photography", "rooftop view", "skyline night",
    "city aerial view", "street photography night", "alley old town", "market street",
    "train station", "airport architecture", "subway station design", "parking garage",
    "industrial building", "warehouse loft", "glass building", "concrete brutalism",
    "art deco building", "victorian house", "colonial architecture", "treehouse design",
    "tiny house", "cabin woods", "modern villa", "penthouse interior",
    "swimming pool luxury", "garden design", "courtyard architecture", "balcony view",
    "fire escape nyc", "neon signs city", "chinatown street", "european village",
    "santorini greece", "venice canal", "paris eiffel tower", "london bridge",
    "new york skyline", "dubai architecture", "singapore skyline", "tokyo street",
    "hong kong density", "istanbul mosque", "barcelona gaudi", "rome colosseum",
    # ── Art & Design ──
    "oil painting classic", "impressionist art", "surrealist painting", "pop art design",
    "art nouveau pattern", "bauhaus design", "minimalist poster", "typography art",
    "calligraphy beautiful", "ink drawing", "pencil sketch portrait", "charcoal drawing",
    "pastel drawing", "acrylic painting", "spray paint art", "mosaic art",
    "stained glass", "sculpture modern", "ceramic pottery", "glass blowing art",
    "metalwork art", "woodwork carving", "paper art origami", "collage art",
    "mixed media art", "installation art", "performance art", "kinetic art",
    "light art installation", "projection mapping", "holographic art", "generative art",
    "pixel art retro", "voxel art", "low poly art", "isometric illustration",
    "vector illustration", "flat design", "material design", "neumorphism design",
    "glassmorphism ui", "gradient mesh", "color palette inspiration", "pattern design",
    "textile pattern", "wallpaper pattern", "mandala art", "zentangle pattern",
    "sacred geometry", "fractal art", "optical illusion", "anamorphic art",
    "trompe loeil", "mural painting", "ceiling art", "floor art 3d",
    # ── Photography styles ──
    "black white photography", "long exposure", "double exposure", "tilt shift",
    "bokeh lights", "silhouette photography", "reflection photography", "shadow play",
    "macro photography", "aerial photography drone", "infrared photography", "film photography",
    "polaroid vintage", "lomo photography", "cross processed photo", "high key photography",
    "low key photography", "hdr photography", "panoramic landscape", "fisheye lens",
    "lens flare", "motion blur", "freeze frame action", "time lapse",
    "light painting", "steel wool photography", "sparkler writing", "fireworks night",
    "smoke art photography", "water splash", "milk drop photography", "powder explosion color",
    "prism photography", "crystal ball photo", "levitation photography", "forced perspective",
    "street portrait candid", "fashion editorial", "beauty photography", "conceptual photography",
    "fine art photography", "documentary photography", "photojournalism", "lifestyle photography",
    "product photography", "flat lay photo", "still life photography", "minimalist photography",
    "symmetry photography", "leading lines composition", "golden ratio photo", "framing photography",
    # ── Fashion & Style ──
    "haute couture fashion", "street style fashion", "vintage fashion", "boho style",
    "punk fashion", "gothic fashion style", "preppy style", "athleisure fashion",
    "minimalist fashion", "maximalist fashion", "y2k fashion", "90s fashion",
    "80s fashion neon", "70s fashion retro", "60s mod fashion", "50s pin up",
    "japanese streetwear", "korean fashion", "scandinavian style", "french fashion",
    "italian fashion", "african fashion print", "indian fashion sari", "middle eastern fashion",
    "sneaker collection", "luxury watches", "jewelry design", "handbag luxury",
    "sunglasses fashion", "hat fashion", "scarf styling", "belt fashion",
    "nail art design", "makeup artistic", "hair style creative", "tattoo design art",
    "piercing fashion", "body art painting", "face paint art", "costume design",
    # ── Food & Drink ──
    "sushi plating", "italian pasta", "french pastry", "mexican food colorful",
    "indian curry", "thai food", "chinese dim sum", "japanese ramen",
    "korean bbq", "mediterranean food", "middle eastern cuisine", "african food",
    "chocolate dessert", "cake decorating", "cupcake design", "macaron colorful",
    "ice cream aesthetic", "smoothie bowl", "acai bowl", "breakfast aesthetic",
    "brunch flatlay", "coffee latte art", "tea ceremony", "cocktail photography",
    "wine glass", "craft beer", "juice fresh", "baking bread",
    "pizza artisan", "burger gourmet", "salad colorful", "soup photography",
    "cheese board", "charcuterie board", "fruit arrangement", "vegetable garden",
    "spice collection", "herb garden", "farmers market", "street food world",
    "food truck", "restaurant interior design", "cafe aesthetic", "bakery display",
    "kitchen design modern", "cooking process", "food styling", "recipe photography",
    # ── Interior & Home ──
    "living room modern", "bedroom cozy", "kitchen interior design", "bathroom luxury",
    "home office design", "reading nook", "walk in closet", "laundry room design",
    "dining room elegant", "nursery room", "kids room design", "teen room",
    "loft apartment", "studio apartment", "bohemian interior", "scandinavian interior",
    "industrial interior", "mid century modern", "art deco interior", "japanese interior",
    "moroccan interior", "rustic farmhouse", "coastal interior", "tropical interior",
    "maximalist interior", "minimalist interior", "dark moody interior", "white interior",
    "colorful interior", "plant interior", "bookshelf styling", "gallery wall",
    "fireplace design", "window seat", "indoor garden", "terrarium design",
    "candle aesthetic", "lamp design", "chandelier luxury", "mirror decorative",
    "rug pattern", "curtain design", "pillow arrangement", "blanket texture",
    "shelf styling", "desk setup", "workspace aesthetic", "gaming room setup",
    # ── Technology & Gadgets ──
    "gaming setup rgb", "pc build custom", "mechanical keyboard", "monitor setup ultrawide",
    "headphones audiophile", "camera gear", "drone photography", "smart home",
    "robot technology", "3d printer", "virtual reality", "augmented reality",
    "hologram technology", "circuit board macro", "cpu chip close up", "fiber optic",
    "server room", "data center", "code on screen", "terminal hacker aesthetic",
    "retro computer", "vintage tech", "synthesizer music", "vinyl record player",
    "cassette tape retro", "vhs aesthetic", "crt monitor retro", "arcade machine",
    "pinball machine", "electric car", "self driving car", "futuristic vehicle",
    "spaceship concept", "rocket launch", "satellite space", "space station",
    # ── Sports & Fitness ──
    "surfing wave", "skateboarding trick", "snowboarding powder", "rock climbing",
    "mountain biking", "road cycling", "running marathon", "swimming pool",
    "yoga pose", "crossfit workout", "boxing training", "martial arts",
    "basketball dunk", "soccer football", "tennis action", "golf course",
    "formula one racing", "motocross action", "parkour urban", "skydiving",
    "bungee jumping", "scuba diving", "kayaking river", "sailing yacht",
    "fishing lake", "horseback riding", "archery target", "fencing sport",
    "ice skating", "figure skating", "skiing alpine", "hockey ice",
    "gymnastics artistic", "dance performance", "ballet dancer", "breakdancing",
    "cheerleading", "wrestling sport", "weightlifting", "triathlon race",
    # ── Music & Entertainment ──
    "concert photography", "music festival", "dj turntable", "guitar close up",
    "piano keys", "violin music", "drums percussion", "microphone vintage",
    "recording studio", "music production", "vinyl collection", "album cover art",
    "band photography", "singer performance", "orchestra symphony", "jazz music",
    "rock concert", "hip hop culture", "edm festival lights", "country music",
    "classical music", "opera house", "theater stage", "cinema aesthetic",
    "movie poster vintage", "film noir", "horror aesthetic", "sci fi concept",
    "fantasy world concept", "steampunk design", "dieselpunk", "solarpunk aesthetic",
    "vaporwave aesthetic", "synthwave art", "retrowave", "outrun aesthetic",
    "lofi aesthetic", "cottagecore", "darkcore aesthetic", "light academia",
    "dark academia", "goblincore", "fairycore", "angelcore aesthetic",
    # ── Science & Education ──
    "chemistry lab", "biology microscope", "physics experiment", "astronomy telescope",
    "dna helix", "atom model", "periodic table", "crystal mineral",
    "fossil paleontology", "dinosaur art", "archaeology discovery", "ancient egypt",
    "ancient greece", "roman empire", "medieval history", "renaissance art",
    "world map vintage", "globe geography", "compass navigation", "telescope stars",
    "microscope cells", "laboratory science", "space exploration", "mars planet",
    "jupiter planet", "saturn rings", "nebula space", "supernova explosion",
    "black hole space", "constellation map", "solar system", "comet tail",
    "asteroid belt", "moon surface", "earth from space", "international space station",
    # ── Seasonal & Holidays ──
    "christmas decoration", "halloween costume", "easter eggs colorful", "valentines day",
    "new year fireworks", "thanksgiving dinner", "fourth july", "st patrick day",
    "chinese new year", "diwali lights", "hanukkah menorah", "ramadan lantern",
    "carnival brazil", "day of dead mexico", "mardi gras", "oktoberfest",
    "spring equinox", "summer vibes", "autumn cozy", "winter wonderland",
    "cherry blossom japan", "fall foliage", "summer beach", "winter cabin",
    "spring garden", "summer pool party", "autumn harvest", "winter sports",
    "holiday lights", "gingerbread house", "snowman decoration", "pumpkin carving",
    # ── Abstract & Conceptual ──
    "abstract smoke color", "liquid art", "paint splatter", "ink water",
    "bubble macro", "glass refraction", "crystal prism rainbow", "oil water macro",
    "rust texture", "peeling paint", "cracked earth", "marble texture",
    "wood grain pattern", "metal texture brushed", "fabric texture close", "leather texture",
    "concrete texture", "sand pattern wind", "wave pattern water", "fire flames close",
    "ice texture frozen", "moss texture green", "bark tree close", "feather macro detail",
    "scale pattern", "honeycomb pattern", "spiral fibonacci", "kaleidoscope pattern",
    "symmetry nature", "asymmetry art", "chaos theory visual", "entropy art",
    "minimalism white", "color explosion", "monochrome art", "duotone design",
    "gradient sunset", "neon gradient", "holographic texture", "iridescent surface",
    "chrome reflection", "mirror infinity", "glass shatter", "paper fold art",
    # ── Travel & Culture ──
    "machu picchu", "great wall china", "taj mahal india", "pyramids egypt",
    "petra jordan", "angkor wat cambodia", "bali temple", "kyoto japan",
    "marrakech morocco", "havana cuba", "rio de janeiro", "cape town south africa",
    "reykjavik iceland", "amalfi coast italy", "swiss alps", "patagonia argentina",
    "new zealand landscape", "australian outback", "maldives overwater", "bora bora",
    "amazon rainforest", "sahara desert", "grand canyon", "niagara falls",
    "victoria falls", "great barrier reef", "galapagos islands", "madagascar wildlife",
    "serengeti migration", "yellowstone geyser", "yosemite valley", "banff canada",
    "scottish highlands", "norwegian fjords", "greek islands", "croatian coast",
    "turkish cappadocia", "georgian mountains", "sri lanka", "nepal himalaya",
    "vietnam rice field", "myanmar temples", "laos luang prabang", "philippines beach",
    "fiji islands", "tonga ocean", "samoa tropical", "tahiti paradise",
    "zanzibar beach", "seychelles island", "mauritius ocean", "reunion island",
    # ── Vehicles & Transportation ──
    "classic car vintage", "sports car luxury", "muscle car american", "jdm car japanese",
    "rally car dirt", "off road truck", "motorcycle chopper", "cafe racer bike",
    "bicycle vintage", "scooter vespa", "van life camper", "rv travel",
    "yacht luxury", "sailboat ocean", "speedboat water", "submarine deep",
    "airplane aviation", "helicopter flight", "hot air balloon", "glider soaring",
    "train locomotive", "bullet train", "steam engine vintage", "tram city",
    "bus double decker", "taxi yellow nyc", "rickshaw asia", "tuk tuk thailand",
    "cable car san francisco", "gondola venice", "ferry boat", "cruise ship",
    # ── Textures & Materials ──
    "velvet texture", "silk fabric", "denim texture", "wool knitting",
    "lace pattern close", "embroidery detail", "beadwork pattern", "sequin sparkle",
    "gold leaf texture", "silver metallic", "copper patina", "bronze sculpture",
    "diamond crystal", "emerald green gem", "ruby red stone", "sapphire blue",
    "pearl white", "opal iridescent", "quartz crystal", "amethyst purple",
    "granite stone", "slate texture", "sandstone wall", "limestone cave",
    "obsidian volcanic", "jade green stone", "turquoise jewelry", "coral natural",
    "shell seashell", "driftwood beach", "bamboo texture", "rattan weave",
    "wicker basket", "ceramic glaze", "porcelain white", "terracotta pot",
    # ── Crafts & DIY ──
    "pottery wheel", "weaving loom", "knitting needles", "crochet pattern",
    "embroidery hoop", "cross stitch", "quilting pattern", "sewing machine",
    "leather craft", "woodworking shop", "metalworking forge", "glass blowing",
    "candle making", "soap making", "jewelry making", "resin art",
    "macrame wall hanging", "tie dye fabric", "batik pattern", "block printing",
    "screen printing", "letterpress", "bookbinding craft", "paper cutting art",
    "rubber stamp", "wax seal letter", "calligraphy pen", "brush lettering",
    "bullet journal", "scrapbook page", "card making", "gift wrapping",
    # ── Digital & 3D Art ──
    "3d render abstract", "blender art", "cinema 4d design", "unreal engine scene",
    "concept art character", "concept art environment", "matte painting", "digital sculpting",
    "zbrush character", "procedural texture", "node based design", "shader art",
    "ray tracing render", "volumetric lighting", "particle effect", "fluid simulation",
    "cloth simulation", "destruction simulation", "smoke simulation 3d", "fire effect 3d",
    "ocean simulation", "terrain generation", "procedural city", "sci fi corridor",
    "space station interior", "alien landscape", "underwater city concept", "floating island",
    "crystal cave fantasy", "mushroom forest", "ancient library fantasy", "dragon concept art",
    "mech robot design", "spaceship interior design", "cyberpunk city", "neon city night",
    # ── Wellness & Lifestyle ──
    "meditation zen", "spa relaxation", "aromatherapy candles", "bath aesthetic",
    "skincare routine", "self care aesthetic", "journal writing", "morning routine",
    "sunset meditation", "beach yoga", "hiking trail", "camping fire",
    "picnic aesthetic", "garden tea party", "reading corner", "coffee morning",
    "sunday brunch", "farmers market haul", "flower arrangement", "plant care",
    "succulent garden", "cactus collection", "terrarium diy", "herb window",
    "sourdough bread", "homemade pasta", "fermenting kimchi", "preserving jam",
    "foraging wild", "mushroom hunting", "birdwatching nature", "stargazing night",
    # ── Miscellaneous unique queries ──
    "abandoned places", "urban exploration", "ghost town", "haunted house",
    "shipwreck underwater", "plane wreck", "rust decay beauty", "reclaimed nature",
    "overgrown building", "moss covered statue", "ivy wall building", "wisteria tunnel",
    "bougainvillea wall", "jacaranda street", "magnolia tree", "sunflower field",
    "poppy field red", "bluebell forest", "orchid exotic", "lotus pond",
    "water lily monet", "cactus flower bloom", "dandelion seeds", "maple leaf autumn",
    "palm tree tropical", "baobab tree africa", "sequoia giant", "bonsai tree art",
    "topiary garden", "zen garden japanese", "english garden", "french garden versailles",
    "dutch windmill tulip", "greek blue door", "moroccan tiles", "portuguese azulejo",
    "indian rangoli", "tibetan mandala", "aboriginal art dots", "native american art",
    "celtic knot pattern", "viking rune", "egyptian hieroglyph", "mayan pyramid",
    "aztec pattern", "inca stonework", "polynesian tattoo", "maori carving",
    "japanese woodblock print", "chinese ink painting", "korean hanbok", "persian miniature",
    "turkish kilim rug", "african mud cloth", "batik indonesian", "ikat weaving",
    "shibori dye", "kintsugi gold repair", "wabi sabi aesthetic", "ikebana flower",
    "origami paper crane", "furoshiki wrapping", "japanese stationery", "kawaii aesthetic",
    "chibi art cute", "studio ghibli aesthetic", "anime scenery", "manga art style",
    "webtoon art", "comic book art", "graphic novel panel", "superhero art",
    "villain character design", "fairy tale illustration", "children book illustration",
    "botanical illustration", "scientific illustration", "medical illustration", "technical drawing",
    "blueprint architecture", "wireframe design", "prototype mockup", "ui design inspiration",
    "app design mobile", "website design modern", "dashboard design", "icon design set",
    "logo design creative", "brand identity", "packaging design", "label design",
    "book cover design", "magazine layout", "editorial design", "infographic design",
    "data visualization", "chart design", "map illustration", "wayfinding signage",
    "exhibition design", "retail store design", "pop up shop", "window display",
    "stage design concert", "set design film", "prop design", "costume design theater",
]

RESULT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "result", "pinterest",
)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_QUALITY_MAP = {"originals": "originals", "736x": "736x", "564x": "564x"}


class PinterestClient:
    """Клиент Pinterest: авторизация email/password + гостевой fallback."""

    BASE = "https://www.pinterest.com"

    def __init__(self, email: str = "", password: str = "", proxy: Optional[str] = None):
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        if proxy:
            parsed = parse_proxy(proxy)
            if parsed:
                self.session.proxies = {"http": parsed, "https": parsed}

        self._app_version = ""
        self._csrf = ""
        self._logged_in = False

    def _init_session(self) -> bool:
        """Получить cookies, CSRF и app_version с главной страницы."""
        try:
            resp = self.session.get(f"{self.BASE}/", timeout=15)
            resp.raise_for_status()

            match = re.search(r'"appVersion":"([^"]+)"', resp.text)
            self._app_version = match.group(1) if match else ""
            self._csrf = self.session.cookies.get("csrftoken", "")

            if not self._csrf:
                log_simple("Не удалось получить CSRF токен", status="error", account_name="Pinterest")
                return False
            return True
        except Exception as e:
            log_simple(f"Ошибка инициализации сессии: {e}", status="error", account_name="Pinterest")
            return False

    def _setup_api_headers(self, source_url: str = "/", handler: str = "www/index.js"):
        """Настроить заголовки для API запросов."""
        self.session.headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": self._csrf,
            "X-APP-VERSION": self._app_version,
            "X-Pinterest-AppState": "active",
            "X-Pinterest-Source-Url": source_url,
            "X-Pinterest-PWS-Handler": handler,
            "Referer": f"{self.BASE}{source_url}",
            "Origin": self.BASE,
        })

    def login(self) -> bool:
        """Авторизация на Pinterest через email/password."""
        if not self._init_session():
            return False

        if not self.email or not self.password:
            log_simple("Логин/пароль не указаны, работаем в гостевом режиме", status="warning", account_name="Pinterest")
            return self._init_guest_mode()

        try:
            # Посетить страницу логина
            self.session.get(f"{self.BASE}/login/", timeout=15)
            self._csrf = self.session.cookies.get("csrftoken", self._csrf)

            self._setup_api_headers("/login/", "www/login.js")
            self.session.headers["Content-Type"] = "application/x-www-form-urlencoded"

            login_data = {
                "source_url": "/login/",
                "data": json.dumps({
                    "options": {
                        "username_or_email": self.email,
                        "password": self.password,
                    },
                    "context": {},
                }),
            }

            resp = self.session.post(
                f"{self.BASE}/resource/UserSessionResource/create/",
                data=login_data,
                timeout=15,
            )

            # Убрать Content-Type чтобы не мешал GET запросам
            self.session.headers.pop("Content-Type", None)

            if resp.status_code == 200:
                data = resp.json()
                error = data.get("resource_response", {}).get("error")
                if error:
                    msg = error.get("message", str(error))
                    # Аккаунт через Google — fallback на гостевой режим
                    if "Google" in msg or "connected" in msg:
                        log_simple(
                            f"Аккаунт привязан к Google. Работаем в гостевом режиме",
                            status="warning", account_name="Pinterest",
                        )
                        return self._init_guest_mode()
                    log_simple(f"Ошибка авторизации: {msg}", status="error", account_name="Pinterest")
                    return False

                self._csrf = self.session.cookies.get("csrftoken", self._csrf)
                self._logged_in = True
                log_simple("Авторизация успешна!", status="success", account_name="Pinterest")
                return True
            else:
                log_simple(f"Ошибка авторизации: HTTP {resp.status_code}", status="error", account_name="Pinterest")
                # Fallback
                return self._init_guest_mode()

        except Exception as e:
            log_simple(f"Ошибка при авторизации: {e}", status="error", account_name="Pinterest")
            return self._init_guest_mode()

    def _init_guest_mode(self) -> bool:
        """Инициализация гостевого режима — работает без логина."""
        try:
            if not self._csrf:
                if not self._init_session():
                    return False
            log_simple("Гостевой режим активирован", status="info", account_name="Pinterest")
            return True
        except Exception:
            return False

    def _visit_search_page(self, query: str):
        """Посетить HTML страницу поиска для получения правильных cookies."""
        try:
            # Временно вернуть HTML Accept
            old_accept = self.session.headers.get("Accept", "")
            self.session.headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            self.session.headers.pop("X-Requested-With", None)

            self.session.get(
                f"{self.BASE}/search/pins/?q={requests.utils.quote(query)}",
                timeout=15,
            )
            self._csrf = self.session.cookies.get("csrftoken", self._csrf)

            self.session.headers["Accept"] = old_accept
        except Exception:
            pass

    def search_images(self, query: str, bookmark: str = "") -> Tuple[List[str], str]:
        """Поиск картинок через Pinterest API."""
        image_urls: list[str] = []
        new_bookmark = ""
        quality = _QUALITY_MAP.get(PINTEREST_IMAGE_QUALITY, "originals")

        source_url = f"/search/pins/?q={requests.utils.quote(query)}"

        # Посещаем HTML страницу поиска перед API запросом (нужно для cookies)
        if not bookmark:
            self._visit_search_page(query)

        self._setup_api_headers(source_url, "www/search/[scope].js")

        options = {
            "query": query,
            "scope": "pins",
            "bookmarks": [bookmark] if bookmark else [],
            "field_set_key": "unauth_react",
        }

        params = {
            "source_url": source_url,
            "data": json.dumps({"options": options, "context": {}}),
            "_": str(int(time.time() * 1000)),
        }

        try:
            resp = self.session.get(
                f"{self.BASE}/resource/BaseSearchResource/get/",
                params=params,
                timeout=15,
            )
            if resp.status_code != 200:
                return image_urls, new_bookmark

            data = resp.json()
            resource = data.get("resource_response", {})
            results = resource.get("data", {}).get("results", [])
            new_bookmark = resource.get("bookmark", "")

            for pin in results:
                if not isinstance(pin, dict):
                    continue

                images = pin.get("images", {})
                url = ""

                # Приоритет: orig > 736x > 564x > 474x
                for size_key in ["orig", "736x", "564x", "474x"]:
                    size_data = images.get(size_key, {})
                    url = size_data.get("url", "")
                    if url:
                        break

                if url and url.startswith("http"):
                    # Конвертируем в нужное качество
                    if quality == "originals":
                        for sz in ["736x", "564x", "474x"]:
                            if f"/{sz}/" in url:
                                url = url.replace(f"/{sz}/", "/originals/")
                                break
                    elif f"/{quality}/" not in url:
                        url = re.sub(r"/(originals|736x|564x|474x)/", f"/{quality}/", url)

                    image_urls.append(url)

        except Exception as e:
            log_simple(f"Ошибка поиска '{query}': {e}", status="warning", account_name="Pinterest")

        return image_urls, new_bookmark

    def close(self):
        self.session.close()


def _collect_image_urls(client: PinterestClient, count: int) -> List[str]:
    """Собрать URL картинок через поиск по нескольким запросам."""
    all_urls: list[str] = []
    seen: set[str] = set()

    user_queries = [q for q in (PINTEREST_SEARCH_QUERIES or []) if isinstance(q, str) and q.strip()]
    target = count * 2

    if user_queries:
        log_simple(
            f"Используем пользовательские запросы: {user_queries}",
            status="info", account_name="Pinterest",
        )

        # Состояние пагинации по каждому запросу (bookmark + признак исчерпания).
        bookmarks: dict[str, str] = {q: "" for q in user_queries}
        exhausted: set[str] = set()
        query_totals: dict[str, int] = {q: 0 for q in user_queries}
        # Ограничение на количество холостых попыток (без новых URL), чтобы не зациклиться.
        idle_attempts = 0
        max_idle = max(10, len(user_queries) * 5)

        with console.status("[bold cyan]Поиск картинок на Pinterest...[/]", spinner="dots"):
            while len(all_urls) < target:
                available = [q for q in user_queries if q not in exhausted]
                if not available:
                    break

                query = random.choice(available)
                bookmark = bookmarks[query]

                urls, new_bookmark = client.search_images(query, bookmark)

                added = 0
                for u in urls:
                    if u not in seen:
                        seen.add(u)
                        all_urls.append(u)
                        added += 1

                query_totals[query] += added

                # Если Pinterest вернул тот же bookmark или пустой — дальнейшая пагинация
                # по этому запросу бесполезна.
                if not new_bookmark or new_bookmark == bookmark:
                    exhausted.add(query)
                else:
                    bookmarks[query] = new_bookmark

                if added > 0:
                    idle_attempts = 0
                    log_simple(
                        f"'{query}': +{added} картинок (всего: {len(all_urls)})",
                        status="success", account_name="Pinterest",
                    )
                else:
                    idle_attempts += 1
                    if idle_attempts >= max_idle:
                        break

                time.sleep(random.uniform(0.5, 1.2))
    else:
        num_queries = min(len(SEARCH_QUERIES), max(3, count // 10 + 3))
        queries = random.sample(SEARCH_QUERIES, num_queries)
        max_pages = max(5, count // (num_queries * 20) + 2)

        with console.status("[bold cyan]Поиск картинок на Pinterest...[/]", spinner="dots"):
            for query in queries:
                if len(all_urls) >= target:
                    break

                bookmark = ""
                query_count = 0
                for _page in range(max_pages):
                    urls, bookmark = client.search_images(query, bookmark)
                    for u in urls:
                        if u not in seen:
                            seen.add(u)
                            all_urls.append(u)
                            query_count += 1

                    if not bookmark or len(all_urls) >= target:
                        break
                    time.sleep(random.uniform(0.5, 1.2))

                if query_count > 0:
                    log_simple(
                        f"'{query}': +{query_count} картинок (всего: {len(all_urls)})",
                        status="success", account_name="Pinterest",
                    )

    random.shuffle(all_urls)
    return all_urls[:count * 3]


def _download_image(session: requests.Session, url: str, filepath: str) -> bool:
    """Скачать картинку. Fallback на 736x если originals недоступен."""
    urls_to_try = [url]
    if "/originals/" in url:
        urls_to_try.append(url.replace("/originals/", "/736x/"))

    for try_url in urls_to_try:
        try:
            resp = session.get(try_url, timeout=25, allow_redirects=True)
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            if "image" not in content_type and "octet-stream" not in content_type:
                continue

            data = resp.content
            if len(data) < 2000:
                continue

            with open(filepath, "wb") as f:
                f.write(data)
            return True
        except Exception:
            continue

    if os.path.exists(filepath):
        os.remove(filepath)
    return False


def _get_extension(url: str) -> str:
    path = url.split("?")[0]
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        if path.lower().endswith(ext):
            return ext
    return ".jpg"


def download_pinterest_images(count: int) -> List[str]:
    """Основная функция: авторизация + поиск + скачивание."""
    os.makedirs(RESULT_DIR, exist_ok=True)

    # Авторизация
    proxies = ProxyManager.get_all()
    proxy = proxies[0] if proxies else None

    client = PinterestClient(PINTEREST_EMAIL, PINTEREST_PASSWORD, proxy)
    if not client.login():
        log_simple("Не удалось подключиться к Pinterest.", status="error", account_name="Pinterest")
        return []

    log_simple(f"Начинаем поиск {count} картинок...", status="info", account_name="Pinterest")

    # Сбор URL
    image_urls = _collect_image_urls(client, count)

    if not image_urls:
        log_simple("Не удалось найти картинки.", status="error", account_name="Pinterest")
        client.close()
        return []

    log_simple(
        f"Найдено {len(image_urls)} URL, скачиваем {count}...",
        status="success", account_name="Pinterest",
    )

    # Скачивание с прогресс-баром
    proxy_index = 0
    downloaded: list[str] = []
    failed = 0
    url_index = 0
    delay_min, delay_max = PINTEREST_DOWNLOAD_DELAY

    progress = Progress(
        SpinnerColumn(style="bold magenta"),
        TextColumn("[bold cyan]{task.description}[/]"),
        BarColumn(bar_width=40, style="magenta", complete_style="bold green", finished_style="bold green"),
        TextColumn("[bold white]{task.completed}/{task.total}[/]"),
        TextColumn("[dim]│[/]"),
        DownloadColumn(),
        TextColumn("[dim]│[/]"),
        TransferSpeedColumn(),
        TextColumn("[dim]│[/]"),
        TimeRemainingColumn(),
        console=console,
    )

    with progress:
        main_task = progress.add_task("📌 Скачивание", total=count)

        while len(downloaded) < count and url_index < len(image_urls):
            url = image_urls[url_index]
            url_index += 1

            # Чередуем прокси для скачивания
            dl_proxy = proxies[proxy_index % len(proxies)] if proxies else None
            proxy_index += 1

            dl_session = requests.Session()
            dl_session.headers["User-Agent"] = random.choice(USER_AGENTS)
            if dl_proxy:
                parsed = parse_proxy(dl_proxy)
                if parsed:
                    dl_session.proxies = {"http": parsed, "https": parsed}

            ext = _get_extension(url)
            filename = f"pinterest_{uuid.uuid4().hex[:10]}{ext}"
            filepath = os.path.join(RESULT_DIR, filename)

            if _download_image(dl_session, url, filepath):
                downloaded.append(filepath)
                progress.update(main_task, advance=1)
                log_task(
                    len(downloaded), count,
                    f"Скачано: {filename}",
                    status="success",
                    account_name="Pinterest",
                )
            else:
                failed += 1

            dl_session.close()
            time.sleep(random.uniform(delay_min, delay_max))

    client.close()

    log_simple(
        f"Готово! Скачано {len(downloaded)}/{count} картинок. Ошибок: {failed}",
        status="success" if downloaded else "error",
        account_name="Pinterest",
    )
    if downloaded:
        log_simple(f"Сохранено в: {RESULT_DIR}", status="info", account_name="Pinterest")

    return downloaded


def create_zip_archive(files: List[str]) -> Optional[str]:
    """Создать ZIP архив из скачанных файлов."""
    if not files:
        return None

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(RESULT_DIR, f"pinterest_{timestamp}.zip")

    with Progress(
        SpinnerColumn(style="bold magenta"),
        TextColumn("[bold cyan]Создание ZIP архива...[/]"),
        BarColumn(bar_width=40, style="magenta", complete_style="bold green", finished_style="bold green"),
        TextColumn("[bold white]{task.completed}/{task.total}[/]"),
        console=console,
    ) as progress:
        task = progress.add_task("📦 Архивация", total=len(files))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath in files:
                if os.path.exists(fpath):
                    zf.write(fpath, os.path.basename(fpath))
                    progress.update(task, advance=1)

    log_simple(f"ZIP архив создан: {zip_path}", status="success", account_name="Pinterest")
    return zip_path


def pinterest_downloader_menu():
    """Меню Pinterest Downloader — вызывается из main.py."""
    from questionary import text, confirm

    console.print("\n[bold magenta]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]")
    console.print("[bold cyan]  📌 Pinterest Random Image Downloader[/]")
    console.print("[bold magenta]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]\n")

    count_str = text(
        "Сколько картинок скачать?",
        default="10",
        qmark="📌",
    ).ask()

    if count_str is None:
        return

    try:
        count = int(count_str)
        if count <= 0:
            raise ValueError
    except ValueError:
        log_simple("Некорректное число.", status="error", account_name="Pinterest")
        return

    if count > PINTEREST_MAX_IMAGES:
        console.print(f"[bold yellow]⚠️  Максимум {PINTEREST_MAX_IMAGES} картинок за раз.[/]")
        count = PINTEREST_MAX_IMAGES

    downloaded = download_pinterest_images(count)

    if downloaded:
        should_zip = confirm(
            "Собрать скачанные картинки в ZIP архив?",
            default=True,
            qmark="📦",
        ).ask()

        if should_zip:
            create_zip_archive(downloaded)

    console.print(f"\n[bold green]✅ Завершено![/] Файлы в: [underline]{RESULT_DIR}[/]\n")
