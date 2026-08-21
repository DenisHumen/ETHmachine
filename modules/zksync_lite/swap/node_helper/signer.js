/**
 * zkSync Lite signer helper.
 *
 * Usage:  node signer.js <COMMAND> '<JSON_INPUT>'
 *
 * Commands:
 *   account-info           {privateKey}
 *       -> {address, accountId, isActive, pubKeyHash, signerPubKeyHash, balances}
 *
 *   change-pubkey          {privateKey, feeToken="ETH"}
 *       -> {txHash}
 *
 *   transfer               {privateKey, to, token, amountRaw, feeToken="ETH", validUntil?}
 *       -> {txHash}
 *
 *   withdraw               {privateKey, ethAddress, token, amountRaw, feeToken="ETH", fastProcessing?:bool}
 *       -> {txHash}
 *
 *   tx-receipt             {txHash}
 *       -> {executed, success, failReason?, block?}
 *
 *   transfer-fee           {to, token, feeToken="ETH"}
 *       -> {feeRaw, feeHuman, decimals}
 *
 *   change-pubkey-fee      {address, feeToken="ETH"}
 *       -> {feeRaw, feeHuman, decimals}
 *
 * Output is a single JSON line on stdout. On any error: {"error": "..."}.
 *
 * NOTE: zksync.js v0.13 uses ethers v5 wallet API.
 * NOTE: proxies are NOT supported here — every request leaves from the host's
 *       real IP. The `proxy` column of data.csv only covers the Layerswap HTTP
 *       client on the Python side.
 */

"use strict";

const zksync = require("zksync");
const { ethers } = require("ethers");

const NETWORK = "mainnet";
const ETH_RPC =
  process.env.ZKSL_L1_RPC ||
  "https://ethereum-rpc.publicnode.com";

let _syncProvider = null;
async function syncProvider() {
  if (_syncProvider) return _syncProvider;
  _syncProvider = await zksync.getDefaultProvider(NETWORK);
  return _syncProvider;
}

function ethProvider() {
  // Pin chainId=1 so ethers doesn't probe the network
  return new ethers.providers.StaticJsonRpcProvider(ETH_RPC, {
    name: "homestead",
    chainId: 1,
  });
}

async function buildWallet(privateKey) {
  const ethW = new ethers.Wallet(privateKey, ethProvider());
  const sp = await syncProvider();
  return await zksync.Wallet.fromEthSigner(ethW, sp);
}

async function ensureSigner(wallet) {
  // For accounts with existing pubkey, set the signer via seed.
  if (!wallet.signer) {
    const { signer } = await zksync.Signer.fromETHSignature(wallet._ethSigner);
    wallet.signer = signer;
  }
}

function out(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

function bad(msg, extra) {
  out(Object.assign({ error: String(msg) }, extra || {}));
  process.exit(1);
}

// ---------- commands ----------

async function cmdAccountInfo(args) {
  const w = await buildWallet(args.privateKey);
  const sp = await syncProvider();
  const state = await sp.getState(w.address());
  const cpkOnchain = state.committed.pubKeyHash;
  let signerPkh = null;
  try {
    const signer = await zksync.Signer.fromETHSignature(w._ethSigner);
    signerPkh = "sync:" + Buffer.from(signer.signer.publicKey().slice(2), "hex").toString("hex").slice(0, 40); // not exact; use lib helper instead
  } catch (_) {}
  // Use library helper to get exact pubkey hash from the sign-key:
  try {
    const signer = (await zksync.Signer.fromETHSignature(w._ethSigner)).signer;
    const pkBytes = await signer.pubKeyHash();
    signerPkh = pkBytes;
  } catch (_) {}

  out({
    address: w.address(),
    accountId: state.id || null,
    isActive:
      cpkOnchain &&
      cpkOnchain !== "sync:0000000000000000000000000000000000000000",
    pubKeyHash: cpkOnchain,
    signerPubKeyHash: signerPkh,
    balances: state.committed.balances,
  });
}

async function cmdChangePubkey(args) {
  const w = await buildWallet(args.privateKey);
  if (!(await w.isSigningKeySet())) {
    const tx = await w.setSigningKey({
      feeToken: args.feeToken || "ETH",
      ethAuthType: "ECDSA",
    });
    const r = await tx.awaitReceipt();
    out({
      txHash: tx.txHash,
      executed: r.executed,
      success: r.success || true,
      failReason: r.failReason || null,
    });
  } else {
    out({ txHash: null, executed: true, success: true, alreadySet: true });
  }
}

async function cmdTransfer(args) {
  const w = await buildWallet(args.privateKey);
  if (!(await w.isSigningKeySet())) {
    bad("ChangePubKey not set; call change-pubkey first");
  }
  const transfer = await w.syncTransfer({
    to: args.to,
    token: args.token,
    amount: ethers.BigNumber.from(args.amountRaw),
    feeToken: args.feeToken || "ETH",
  });
  out({ txHash: transfer.txHash });
}

async function cmdWithdraw(args) {
  const w = await buildWallet(args.privateKey);
  if (!(await w.isSigningKeySet())) {
    bad("ChangePubKey not set; call change-pubkey first");
  }
  const wd = await w.withdrawFromSyncToEthereum({
    ethAddress: args.ethAddress,
    token: args.token,
    amount: ethers.BigNumber.from(args.amountRaw),
    feeToken: args.feeToken || "ETH",
    fastProcessing: !!args.fastProcessing,
  });
  out({ txHash: wd.txHash });
}

async function cmdTxReceipt(args) {
  const sp = await syncProvider();
  const r = await sp.getTxReceipt(args.txHash);
  out({
    executed: !!r.executed,
    success: r.executed ? !!r.success : null,
    failReason: r.failReason || null,
    block: r.block || null,
  });
}

async function cmdTransferFee(args) {
  const sp = await syncProvider();
  const feeToken = args.feeToken || "ETH";
  const fee = await sp.getTransactionFee("Transfer", args.to, feeToken);
  const decimals = sp.tokenSet.resolveTokenDecimals(feeToken);
  out({
    feeRaw: fee.totalFee.toString(),
    feeHuman: ethers.utils.formatUnits(fee.totalFee, decimals),
    decimals,
  });
}

async function cmdChangePubkeyFee(args) {
  const sp = await syncProvider();
  const feeToken = args.feeToken || "ETH";
  const fee = await sp.getTransactionFee(
    { ChangePubKey: { onchainPubkeyAuth: false } },
    args.address,
    feeToken,
  );
  const decimals = sp.tokenSet.resolveTokenDecimals(feeToken);
  out({
    feeRaw: fee.totalFee.toString(),
    feeHuman: ethers.utils.formatUnits(fee.totalFee, decimals),
    decimals,
  });
}

async function cmdWithdrawFee(args) {
  const sp = await syncProvider();
  const feeToken = args.feeToken || "ETH";
  const txType = args.fastProcessing ? "FastWithdraw" : "Withdraw";
  const fee = await sp.getTransactionFee(txType, args.ethAddress, feeToken);
  const decimals = sp.tokenSet.resolveTokenDecimals(feeToken);
  out({
    feeRaw: fee.totalFee.toString(),
    feeHuman: ethers.utils.formatUnits(fee.totalFee, decimals),
    decimals,
    txType,
  });
}

// ---------- entry ----------

(async () => {
  const cmd = process.argv[2];
  let args = {};
  if (process.argv[3]) {
    try {
      args = JSON.parse(process.argv[3]);
    } catch (e) {
      bad("invalid json arg");
    }
  }
  try {
    switch (cmd) {
      case "account-info":
        return await cmdAccountInfo(args);
      case "change-pubkey":
        return await cmdChangePubkey(args);
      case "transfer":
        return await cmdTransfer(args);
      case "withdraw":
        return await cmdWithdraw(args);
      case "tx-receipt":
        return await cmdTxReceipt(args);
      case "transfer-fee":
        return await cmdTransferFee(args);
      case "change-pubkey-fee":
        return await cmdChangePubkeyFee(args);
      case "withdraw-fee":
        return await cmdWithdrawFee(args);
      default:
        bad(`unknown command: ${cmd}`);
    }
  } catch (e) {
    bad(e && e.message ? e.message : String(e), {
      stack: e && e.stack ? e.stack.split("\n").slice(0, 5).join(" | ") : null,
    });
  } finally {
    try {
      const sp = await syncProvider();
      await sp.disconnect();
    } catch (_) {}
  }
})();
