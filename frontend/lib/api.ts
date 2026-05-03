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
  party_acronym: string | null;
  behavioral_cluster_id: string | null;
  const_alignment_score: number | null;
  party_discipline_score: number | null;
  absence_rate: number | null;
  // Detail endpoint only — full-population vote summary
  votes_sim?: number;
  votes_nao?: number;
  votes_abstencao?: number;
  votes_ausente?: number;
  votes_obstrucao?: number;
  votes_total?: number;
}

export interface ClusterMemberPreview {
  id: string;
  name: string;
  state_uf: string | null;
  photo_url: string | null;
  party_acronym: string | null;
}

export interface ClusterMember {
  id: string;
  name: string;
  state_uf: string | null;
  party: string | null;
  photo_url: string | null;
}

export interface BehavioralCluster {
  id: string;
  label: string | null;
  description: string | null;
  dominant_themes: string[] | null;
  member_count: number | null;
  cohesion_score: number | null;
  algorithm: string | null;
  algorithm_params: Record<string, unknown> | null;
  computed_at: string | null;
  party_distribution: Record<string, number>;
  top_members: ClusterMemberPreview[];
}

export interface ClusterMembersResponse {
  cluster_id: string;
  cluster_label: string | null;
  member_count: number | null;
  cohesion_score: number | null;
  members: ClusterMember[];
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

export interface DonorBucket {
  bucket: "party_fund" | "individual" | "company" | "other";
  donor_count: number;
  total_brl: number;
}
export interface DonorSector {
  sector: string | null;
  donor_count: number;
  total_brl: number;
  top_donor_names: string[];
}
export interface NamedDonor {
  name: string;
  sector: string | null;
  entity_type: "pessoa_fisica" | "pessoa_juridica" | null;
  total_brl: number;
}
export interface SectorVoteCorrelation {
  sector: string;
  amount_brl: number;
  themes: string[];
  votes: {
    sim: number;
    nao: number;
    abstencao: number;
    ausente: number;
    total: number;
  };
}
export interface LegislatorDonors {
  legislator_id: string;
  total_received_brl: number;
  funding_breakdown: DonorBucket[];
  sector_breakdown: DonorSector[];
  top_donors: NamedDonor[];
  correlations: SectorVoteCorrelation[];
}

export const getLegislatorDonors = (id: string) =>
  apiFetch<LegislatorDonors>(`/legislators/${id}/donors`);

export interface SimilarVoter {
  id: string;
  name: string;
  state_uf: string | null;
  photo_url: string | null;
  party: string | null;
  cluster_id: string | null;
  cluster_label: string | null;
  similarity_pct: number | null;
  shared_votes: number;
  agreements: number;
}
export const getSimilarVoters = (id: string) =>
  apiFetch<{ legislator_id: string; items: SimilarVoter[]; count: number }>(
    `/legislators/${id}/similar-voters`,
  );

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

export interface FeaturedBill {
  id?: string;
  camara_id: number;
  type?: string | null;
  number?: number;
  year?: number;
  title?: string | null;
  status?: string | null;
  const_risk_score?: number | null;
  theme_tags?: string[] | null;
  votes_sim?: number;
  votes_nao?: number;
  votes_abstencao?: number;
  votes_obstrucao?: number;
  votes_ausente?: number;
  votes_total?: number;
  not_in_db?: boolean;
}

export const getFeaturedBills = (camaraIds: number[]) =>
  apiFetch<{ items: FeaturedBill[] }>(
    `/bills/featured?ids=${camaraIds.join(",")}`,
  );

// Stats (homepage hero)
export interface SiteStats {
  legislators: number;
  bills: number;
  votes: number;
  clusters: number;
}
export const getStats = () => apiFetch<SiteStats>(`/stats`);

// Clusters
export const getClusters = () =>
  apiFetch<{ clusters: BehavioralCluster[] }>(`/clusters`);

export const getClusterMembers = (clusterId: string) =>
  apiFetch<ClusterMembersResponse>(`/clusters/${clusterId}/members`);

// Analysis (the /analises page)
export interface ScatterPoint {
  id: string;
  name: string;
  state_uf: string | null;
  party: string | null;
  cluster_id: string | null;
  cluster_label: string | null;
  discipline: number;        // 0..1
  const_alignment: number;   // -1..+1
  absence_rate: number | null;
}

export const getDisciplineAlignmentScatter = () =>
  apiFetch<{ items: ScatterPoint[]; total: number }>(
    `/analysis/scatter-discipline-alignment`,
  );

export interface HeatmapCell {
  sector: string;
  theme: string;
  sim: number;
  nao: number;
  total: number;
  deputies: number;
  pct_sim: number | null;
}
export interface DonorVoteHeatmap {
  sectors: string[];
  themes: string[];
  cells: HeatmapCell[];
}

export const getDonorVoteHeatmap = () =>
  apiFetch<DonorVoteHeatmap>(`/analysis/donor-vote-heatmap`);

export interface StateClusterCount {
  cluster_id: string | null;
  cluster_label: string;
  deputy_count: number;
}
export interface StateTopDeputy {
  id: string;
  name: string;
  photo_url: string | null;
  party: string | null;
  cluster_label: string | null;
  const_alignment: number | null;
}
export interface StateProfile {
  uf: string;
  deputy_count: number;
  dominant_cluster: string | null;  // "Misto" if no cluster ≥ 40%
  clusters: StateClusterCount[];
  avg_const_alignment: number | null;
  avg_discipline: number | null;
  avg_absence: number | null;
  parties: string[];
  top_deputies: StateTopDeputy[];
}

export const getStateProfiles = () =>
  apiFetch<{ items: StateProfile[]; total: number }>(`/analysis/state-profiles`);
