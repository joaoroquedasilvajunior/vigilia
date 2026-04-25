const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

export interface Legislator {
  id: string;
  camara_id: number | null;
  name: string;
  display_name: string | null;
  chamber: "camara" | "senado" | null;
  state_uf: string;
  photo_url: string | null;
  const_alignment_score: number | null;
  party_discipline_score: number | null;
  absence_rate: number | null;
}

export interface Bill {
  id: string;
  camara_id: number | null;
  type: string | null;
  number: number;
  year: number;
  title: string;
  status: string | null;
  urgency_regime: boolean;
  secrecy_vote: boolean;
  const_risk_score: number | null;
  theme_tags: string[] | null;
  presentation_date: string | null;
  summary_official?: string | null;
  summary_ai?: string | null;
  full_text_url?: string | null;
  affected_articles?: string[] | null;
}

export interface PaginatedResponse<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export interface VoteWithBill {
  vote_value: string;
  voted_at: string | null;
  followed_party_line: boolean | null;
  donor_conflict_flag: boolean;
  const_conflict_flag: boolean;
  bill: Pick<Bill, "id" | "type" | "number" | "year" | "title" | "status" | "const_risk_score" | "theme_tags">;
}

// Legislators
export const getLegislators = (params?: {
  state?: string;
  party?: string;
  chamber?: string;
  page?: number;
  page_size?: number;
}) => {
  const qs = new URLSearchParams(
    Object.fromEntries(
      Object.entries(params ?? {})
        .filter(([, v]) => v !== undefined && v !== "")
        .map(([k, v]) => [k, String(v)])
    )
  ).toString();
  return apiFetch<PaginatedResponse<Legislator>>(`/legislators${qs ? `?${qs}` : ""}`);
};

export const getLegislator = (id: string) =>
  apiFetch<Legislator>(`/legislators/${id}`);

export const getLegislatorVotes = (id: string, page = 1) =>
  apiFetch<PaginatedResponse<VoteWithBill>>(`/legislators/${id}/votes?page=${page}`);

// Bills
export const getBills = (params?: {
  type?: string;
  status?: string;
  theme?: string;
  high_risk?: boolean;
  page?: number;
  page_size?: number;
}) => {
  const qs = new URLSearchParams(
    Object.fromEntries(
      Object.entries(params ?? {})
        .filter(([, v]) => v !== undefined && v !== "")
        .map(([k, v]) => [k, String(v)])
    )
  ).toString();
  return apiFetch<PaginatedResponse<Bill>>(`/bills${qs ? `?${qs}` : ""}`);
};

export const getBill = (id: string) => apiFetch<Bill>(`/bills/${id}`);
