// Typed client for the STRIX finance API (/api/finance/*). Money is carried as
// strings end to end (never a JS number) to preserve exact Decimal values.

export interface Account {
  account_id: string;
  name: string;
  account_type: string;
  owner: string;
  institution: string;
  mask: string;
  currency: string;
  status: string;
  opening_balance: string;
}

export interface AccountBalance {
  account_id: string;
  name: string;
  account_type: string;
  balance: string;
}

export interface NetWorth {
  assets_total: string;
  liabilities_total: string;
  net_worth: string;
  accounts: AccountBalance[];
}

export interface Transaction {
  txn_id: string;
  account_id: string;
  posted_date: string;
  amount: string;
  description: string;
  owned: boolean;
}

export interface TransactionPage {
  items: Transaction[];
  total: number;
  limit: number;
  offset: number;
}

export interface IncomeExpense {
  start: string;
  end: string;
  inflow: string;
  outflow: string;
  net: string;
  transaction_count: number;
}

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export async function getAccounts(owner?: string): Promise<Account[]> {
  const q = owner ? `?owner=${encodeURIComponent(owner)}` : "";
  const data = await json<{ accounts: Account[] }>(await fetch(`/api/finance/accounts${q}`));
  return data.accounts;
}

export async function getNetWorth(): Promise<NetWorth> {
  return json<NetWorth>(await fetch("/api/finance/net-worth"));
}

export async function createAccount(body: {
  name: string;
  account_type: string;
  owner: string;
  opening_balance: string;
  institution?: string;
  mask?: string;
  currency?: string;
}): Promise<Account> {
  return json<Account>(
    await fetch("/api/finance/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function getTransactions(params: {
  accountId?: string;
  start?: string;
  end?: string;
  limit?: number;
  offset?: number;
}): Promise<TransactionPage> {
  const qs = new URLSearchParams();
  if (params.accountId) qs.set("account_id", params.accountId);
  if (params.start) qs.set("start", params.start);
  if (params.end) qs.set("end", params.end);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return json<TransactionPage>(await fetch(`/api/finance/transactions${q ? `?${q}` : ""}`));
}

export async function getIncomeExpense(start: string, end: string): Promise<IncomeExpense> {
  const qs = new URLSearchParams({ start, end });
  return json<IncomeExpense>(await fetch(`/api/finance/income-expense?${qs.toString()}`));
}
