export type Operation = "BUY" | "SELL";

export type OrderType = "MKT" | "LMT";

export interface OrderPayload {
  orderId: string;
  op: Operation;
  quantity: number;
  symbol: string;
  exchange: string;
  orderType: OrderType;
  limitPrice?: number;
}
