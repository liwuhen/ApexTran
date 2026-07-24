// A stock is identified by (market, symbol) everywhere in the market module —
// the symbol alone is ambiguous. These two helpers are the single spelling of
// that pair: `marketRefKey` for indexing it client-side, `marketRef` for the
// wire format the backend's batch endpoints parse ("market:symbol").

export type MarketRef = {
  market?: string;
  symbol: string;
};

export function marketRefKey(ref: MarketRef): string {
  return `${(ref.market ?? "").trim()}:${ref.symbol.trim()}`;
}

export function marketRef(ref: MarketRef): string {
  const market = (ref.market ?? "").trim();
  const symbol = ref.symbol.trim();
  return market ? `${market}:${symbol}` : symbol;
}
