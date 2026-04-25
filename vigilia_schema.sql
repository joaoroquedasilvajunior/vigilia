-- ============================================================
-- Vigília — PostgreSQL Schema
-- Brazilian Legislative Monitoring System
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── CORE TABLES ───────────────────────────────────────────────

CREATE TABLE parties (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  acronym           VARCHAR(20) UNIQUE NOT NULL,
  name              TEXT,
  founded_date      DATE,
  tse_number        INTEGER,
  ideological_self  VARCHAR(50),
  actual_position   FLOAT CHECK (actual_position BETWEEN -1 AND 1),
  cohesion_score    FLOAT CHECK (cohesion_score BETWEEN 0 AND 1),
  member_count      INTEGER,
  updated_at        TIMESTAMP DEFAULT NOW()
);

CREATE TABLE behavioral_clusters (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  label            VARCHAR(100),
  description      TEXT,
  dominant_themes  TEXT[],
  member_count     INTEGER,
  cohesion_score   FLOAT,
  algorithm        VARCHAR(50),
  algorithm_params JSONB,
  computed_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE themes (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug        VARCHAR(50) UNIQUE NOT NULL,
  label_pt    VARCHAR(100) NOT NULL,
  description TEXT,
  cf_domain   VARCHAR(50)
);

-- Seed themes
INSERT INTO themes (slug, label_pt, cf_domain) VALUES
  ('trabalho', 'Trabalho e Previdência', 'direitos_sociais'),
  ('meio-ambiente', 'Meio Ambiente', 'ordem_economica'),
  ('saude', 'Saúde', 'direitos_sociais'),
  ('educacao', 'Educação', 'direitos_sociais'),
  ('seguranca-publica', 'Segurança Pública', 'seguranca_publica'),
  ('agronegocio', 'Agronegócio e Terra', 'ordem_economica'),
  ('tributacao', 'Tributação', 'tributario'),
  ('direitos-lgbtqia', 'Direitos LGBTQIA+', 'direitos_fundamentais'),
  ('armas', 'Armas e Segurança', 'ordem_social'),
  ('religiao', 'Laicidade e Religião', 'direitos_fundamentais'),
  ('indigenas', 'Povos Indígenas', 'ordem_social'),
  ('midia', 'Mídia e Comunicação', 'comunicacao'),
  ('reforma-politica', 'Reforma Política', 'organizacao_estado');

CREATE TABLE constitution_articles (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  article_ref     VARCHAR(20) NOT NULL,
  title           VARCHAR(200),
  text_full       TEXT NOT NULL,
  domain          VARCHAR(50),
  theme_tags      TEXT[],
  stf_precedents  JSONB DEFAULT '[]',
  is_fundamental  BOOLEAN DEFAULT FALSE,
  created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE legislators (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  camara_id             INTEGER UNIQUE,
  senado_id             INTEGER UNIQUE,
  name                  VARCHAR(200) NOT NULL,
  display_name          VARCHAR(100),
  chamber               VARCHAR(10) CHECK (chamber IN ('camara', 'senado')),
  state_uf              CHAR(2) NOT NULL,
  nominal_party_id      UUID REFERENCES parties(id),
  education_level       VARCHAR(100),
  declared_assets_brl   NUMERIC(18,2),
  term_start            DATE,
  term_end              DATE,
  photo_url             TEXT,
  cpf_hash              VARCHAR(64),
  -- Computed by analytics pipeline
  behavioral_cluster_id UUID REFERENCES behavioral_clusters(id),
  const_alignment_score FLOAT CHECK (const_alignment_score BETWEEN -1 AND 1),
  party_discipline_score FLOAT CHECK (party_discipline_score BETWEEN 0 AND 1),
  absence_rate          FLOAT CHECK (absence_rate BETWEEN 0 AND 1),
  updated_at            TIMESTAMP DEFAULT NOW()
);

CREATE TABLE sessions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  camara_id   INTEGER UNIQUE,
  session_date DATE NOT NULL,
  type        VARCHAR(50),
  description TEXT
);

CREATE TABLE bills (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  camara_id         INTEGER UNIQUE,
  type              VARCHAR(10) CHECK (type IN ('PL','PEC','MPV','PDL','PLP','MSC')),
  number            INTEGER NOT NULL,
  year              INTEGER NOT NULL,
  title             TEXT NOT NULL,
  summary_official  TEXT,
  summary_ai        TEXT,
  full_text_url     TEXT,
  status            VARCHAR(80),
  urgency_regime    BOOLEAN DEFAULT FALSE,
  secrecy_vote      BOOLEAN DEFAULT FALSE,
  author_id         UUID REFERENCES legislators(id),
  author_type       VARCHAR(20) DEFAULT 'legislator',
  presentation_date DATE,
  final_vote_date   DATE,
  -- Analysis fields (computed)
  const_risk_score  FLOAT CHECK (const_risk_score BETWEEN 0 AND 1),
  media_coverage_score INTEGER DEFAULT 0,
  theme_tags        TEXT[],
  affected_articles TEXT[],
  created_at        TIMESTAMP DEFAULT NOW(),
  updated_at        TIMESTAMP DEFAULT NOW()
);

CREATE TABLE votes (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  legislator_id       UUID REFERENCES legislators(id) NOT NULL,
  bill_id             UUID REFERENCES bills(id) NOT NULL,
  session_id          UUID REFERENCES sessions(id),
  vote_value          VARCHAR(15) CHECK (vote_value IN ('sim','não','abstencao','obstrucao','ausente')),
  voted_at            TIMESTAMP,
  party_orientation   VARCHAR(15) CHECK (party_orientation IN ('sim','não','livre','obstrucao')),
  followed_party_line BOOLEAN,
  donor_conflict_flag BOOLEAN DEFAULT FALSE,
  const_conflict_flag BOOLEAN DEFAULT FALSE,
  UNIQUE(legislator_id, bill_id)
);

-- ── ENRICHMENT TABLES ─────────────────────────────────────────

CREATE TABLE donors (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cnpj_cpf_hash     VARCHAR(64) UNIQUE,
  name              TEXT NOT NULL,
  entity_type       VARCHAR(20) CHECK (entity_type IN ('pessoa_fisica','pessoa_juridica')),
  sector_cnae       VARCHAR(20),
  sector_group      VARCHAR(50),
  state_uf          CHAR(2),
  total_donated_brl NUMERIC(18,2) DEFAULT 0
);

CREATE TABLE donor_links (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  legislator_id  UUID REFERENCES legislators(id) NOT NULL,
  donor_id       UUID REFERENCES donors(id) NOT NULL,
  amount_brl     NUMERIC(18,2) NOT NULL,
  election_year  INTEGER NOT NULL,
  donation_type  VARCHAR(50),
  source_doc_ref TEXT,
  UNIQUE(legislator_id, donor_id, election_year, donation_type)
);

CREATE TABLE bill_constitution_mapping (
  bill_id              UUID REFERENCES bills(id),
  article_id           UUID REFERENCES constitution_articles(id),
  relationship         VARCHAR(20) CHECK (relationship IN ('compatible','conflicts','amends','regulates')),
  ai_confidence        FLOAT CHECK (ai_confidence BETWEEN 0 AND 1),
  reviewed_by_expert   BOOLEAN DEFAULT FALSE,
  expert_note          TEXT,
  expert_reviewed_at   TIMESTAMP,
  PRIMARY KEY (bill_id, article_id)
);

CREATE TABLE legislator_themes (
  legislator_id    UUID REFERENCES legislators(id),
  theme_id         UUID REFERENCES themes(id),
  votes_favorable  INTEGER DEFAULT 0,
  votes_against    INTEGER DEFAULT 0,
  abstentions      INTEGER DEFAULT 0,
  absences         INTEGER DEFAULT 0,
  position_score   FLOAT CHECK (position_score BETWEEN -1 AND 1),
  last_updated     TIMESTAMP DEFAULT NOW(),
  PRIMARY KEY (legislator_id, theme_id)
);

-- ── INDEXES ───────────────────────────────────────────────────

CREATE INDEX idx_votes_legislator ON votes(legislator_id);
CREATE INDEX idx_votes_bill ON votes(bill_id);
CREATE INDEX idx_votes_value ON votes(vote_value);
CREATE INDEX idx_votes_donor_flag ON votes(donor_conflict_flag) WHERE donor_conflict_flag = TRUE;
CREATE INDEX idx_bills_status ON bills(status);
CREATE INDEX idx_bills_type_year ON bills(type, year);
CREATE INDEX idx_bills_tags ON bills USING GIN(theme_tags);
CREATE INDEX idx_bills_risk ON bills(const_risk_score) WHERE const_risk_score > 0.5;
CREATE INDEX idx_legislators_cluster ON legislators(behavioral_cluster_id);
CREATE INDEX idx_legislators_state ON legislators(state_uf);
CREATE INDEX idx_donor_links_year ON donor_links(election_year);
CREATE INDEX idx_donors_sector ON donors(sector_group);
CREATE INDEX idx_cf_articles_tags ON constitution_articles USING GIN(theme_tags);

-- ── VIEWS ─────────────────────────────────────────────────────

-- Convenience view: legislator + party + cluster
CREATE VIEW v_legislators_full AS
SELECT
  l.*,
  p.acronym AS party_acronym,
  p.name AS party_name,
  p.actual_position AS party_actual_position,
  bc.label AS cluster_label,
  bc.dominant_themes AS cluster_themes
FROM legislators l
LEFT JOIN parties p ON l.nominal_party_id = p.id
LEFT JOIN behavioral_clusters bc ON l.behavioral_cluster_id = bc.id;

-- Convenience view: bills with constitutional risk summary
CREATE VIEW v_bills_with_risk AS
SELECT
  b.*,
  COUNT(bcm.article_id) FILTER (WHERE bcm.relationship = 'conflicts') AS conflicting_articles_count,
  COUNT(bcm.article_id) FILTER (WHERE bcm.reviewed_by_expert = TRUE) AS expert_reviewed_count
FROM bills b
LEFT JOIN bill_constitution_mapping bcm ON b.id = bcm.bill_id
GROUP BY b.id;

-- Convenience view: donor exposure per legislator (aggregated by sector)
CREATE VIEW v_legislator_donor_exposure AS
SELECT
  dl.legislator_id,
  d.sector_group,
  COUNT(DISTINCT d.id) AS donor_count,
  SUM(dl.amount_brl) AS total_received_brl,
  MAX(dl.election_year) AS most_recent_election
FROM donor_links dl
JOIN donors d ON dl.donor_id = d.id
GROUP BY dl.legislator_id, d.sector_group;
