// OFFLINE SELF-TEST — proves the SDK order-build + EIP-712 signing path works
// with ZERO network calls and ZERO real keys. Uses the well-known public test
// key from 1inch's own README. Nothing here can move money.
import { LimitOrder, MakerTraits, Address, randBigInt } from "@1inch/limit-order-sdk";
import { Wallet } from "ethers";

const TEST_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"; // public test key (1inch README)
const maker = new Wallet(TEST_KEY);

const UINT_40_MAX = (1n << 40n) - 1n;
const expiration = BigInt(Math.floor(Date.now() / 1000)) + 3600n;

const makerTraits = MakerTraits.default()
  .withExpiration(expiration)
  .withNonce(randBigInt(UINT_40_MAX));

// Shape of a RAXOL take-profit: sell RAXOL (maker) for USDC (taker) on chain 4663.
// Addresses below are the REAL verified RAXOL + a placeholder taker for the test.
const order = new LimitOrder(
  {
    makerAsset: new Address("0xf44702b17d9abD53815F703e772F35E9c71A53af"), // RAXOL (verified)
    takerAsset: new Address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"), // placeholder (Base USDC addr) — selftest only
    makingAmount: 10_000_000_000_000_000_000_000n, // 10,000 RAXOL (assuming 18 dec — resolve real decimals before arming)
    takingAmount: 20_000_000n, // 20 USDC (6 dec)
    maker: new Address(maker.address),
  },
  makerTraits
);

const chainIds = [8453, 4663];
for (const chainId of chainIds) {
  const typedData = order.getTypedData(chainId);
  const signature = await maker.signTypedData(
    typedData.domain,
    { Order: typedData.types.Order },
    typedData.message
  );
  console.log(`chain ${chainId}:`);
  console.log(`  domain: ${typedData.domain.name} v${typedData.domain.version} chainId=${typedData.domain.chainId}`);
  console.log(`  verifyingContract: ${typedData.domain.verifyingContract}`);
  console.log(`  orderHash: ${order.getOrderHash(chainId)}`);
  console.log(`  signature: ${signature.slice(0, 20)}… (${signature.length} chars) ✓`);
}
console.log("\nOFFLINE SELFTEST PASS — build + sign path works for both chains. No network was touched.");
