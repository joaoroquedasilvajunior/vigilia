# Vigília — Sistema de Monitoramento Legislativo Brasileiro
## Architecture Document v0.1

---

## 1. DATA MODEL

### Philosophy

The central design decision is **behavior over affiliation**. Party labels in Brazil are
near-meaningless for predicting voting behavior. The schema is built to make *what legislators
actually do* the primary organizing principle, not party membership.

All public identifiers (CPF, CNPJ) are stored as SHA-256 hashes to prevent PII exposure
while still allowing cross-referencing across datasets.

---

### Core Entities

#### `legislators`
The fundamental actor table. Covers both deputies (Câmara) and senators.

```sql
CREATE TABLE legislators (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  camara_id            INTEGER UNIQUE,          -- API ID from dadosabertos.camara.leg.br
  senado_id            INTEGER UNIQUE,          -- API ID from legis.senado.leg.br
  name                 VARCHAR(200) NOT NULL,
  display_name         VARCHAR(100),            -- "nome parlamentar"
  chamber              VARCHAR(10) CHECK (chamber IN ('camara', 'senado')),
  state_uf             CHAR(2) NOT NULL,
  nominal_party_id     UUID REFERENCES parties(id),
  education_level      VARCHAR(100),
  declared_assets_brl  NUMERIC(18,2),           -- TSE declared wealth
  term_start           DATE,
  term_end             DATE,
  photo_url            TEXT,
  cpf_hash             VARCHAR(64),             -- SHA-256, never store raw CPF
  -- Computed / updated by analytics pipeline
  behavioral_cluster_id UUID REFERENCES behavioral_clusters(id),
  const_alignment_score FLOAT CHECK (const_alignment_score BETWEEN -1 AND 1),
  party_discipline_score FLOAT CHECK (party_discipline_score BETWEEN 0 AND 1),
  absence_rate          FLOAT,
  updated_at            TIMESTAMP DEFAULT NOW()
);
```

#### `bills`
Any legislative proposal: PL, PEC, MPV, PDL, etc.

```sql
CREATE TABLE bills (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  camara_id         INTEGER UNIQUE,
  type              VARCHAR(10) CHECK (type IN ('PL','PEC','MPV','PDL','PLP','MSC')),
  number            INTEGER NOT NULL,
  year              INTEGER NOT NULL,
  title             TEXT NOT NULL,
  summary_official  TEXT,                     -- Câmara's official summary
  summary_ai        TEXT,                     -- AI-generated plain-language summary
  full_text_url     TEXT,
  status            VARCHAR(50),             -- 'Em tramitação', 'Aprovado', 'Arquivado'...
  urgency_regime    BOOLEAN DEFAULT FALSE,   -- regime de urgência — bypasses committee
  secrecy_vote      BOOLEAN DEFAULT FALSE,   -- votação secreta
  author_id         UUID REFERENCES legislators(id),
  author_type       VARCHAR(20),             -- 'legislator', 'executive', 'judiciary'
  presentation_date DATE,
  final_vote_date   DATE,
  -- Computed by analysis pipeline
  const_risk_score  FLOAT CHECK (const_risk_score BETWEEN 0 AND 1),
  media_coverage_score INTEGER DEFAULT 0,   -- proxy for public awareness
  theme_tags        TEXT[],                 -- NLP-assigned
  affected_articles TEXT[],               -- CF/88 articles implicated
  created_at        TIMESTAMP DEFAULT NOW()
);
```

#### `votes`
Individual legislator votes on bills. The heart of the system.

```sql
CREATE TABLE votes (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  legislator_id       UUID REFERENCES legislators(id) NOT NULL,
  bill_id             UUID REFERENCES bills(id) NOT NULL,
  session_id          UUID REFERENCES sessions(id),
  vote_value          VARCHAR(10) CHECK (vote_value IN ('sim','não','abstencao','obstrucao','ausente')),
  voted_at            TIMESTAMP,
  party_orientation   VARCHAR(10) CHECK (party_orientation IN ('sim','não','livre','obstrucao')),
  -- Computed flags
  followed_party_line BOOLEAN,              -- did they follow their party's orientation?
  donor_conflict_flag BOOLEAN DEFAULT FALSE, -- flagged if major donor benefits from this vote
  const_conflict_flag BOOLEAN DEFAULT FALSE, -- flagged if bill has high constitutional risk
  UNIQUE(legislator_id, bill_id)
);
```

#### `sessions`
Legislative sessions in which votes occur.

```sql
CREATE TABLE sessions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  camara_id    INTEGER UNIQUE,
  date         DATE NOT NULL,
  type         VARCHAR(50),   -- 'Plenária', 'Comissão'
  description  TEXT
);
```

---

### Enrichment Entities

#### `parties`
```sql
CREATE TABLE parties (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  acronym          VARCHAR(20) UNIQUE NOT NULL,
  name             TEXT,
  founded_date     DATE,
  tse_number       INTEGER,
  ideological_self VARCHAR(50),   -- party's self-declared position
  -- Computed from actual voting patterns:
  actual_position  FLOAT,         -- -1 (left) to 1 (right), derived from votes
  cohesion_score   FLOAT,         -- how often members vote together
  member_count     INTEGER
);
```

#### `themes`
```sql
CREATE TABLE themes (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug        VARCHAR(50) UNIQUE NOT NULL,  -- e.g. 'trabalho', 'meio-ambiente'
  label_pt    VARCHAR(100),
  description TEXT,
  -- Maps to CF/88 domain
  cf_domain   VARCHAR(50)
);
```

#### `constitution_articles`
The CF/88 as structured data. Foundational for constitutional scoring.

```sql
CREATE TABLE constitution_articles (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  article_ref     VARCHAR(20) NOT NULL,   -- e.g. 'Art. 7', 'Art. 196'
  title           VARCHAR(200),
  text_full       TEXT NOT NULL,
  domain          VARCHAR(50),            -- 'direitos_fundamentais', 'tributario', etc.
  theme_tags      TEXT[],
  stf_precedents  JSONB,                  -- relevant STF decisions (citations only)
  is_fundamental  BOOLEAN DEFAULT FALSE,  -- cláusula pétrea?
  created_at      TIMESTAMP DEFAULT NOW()
);
```

#### `donors`
Electoral financing from TSE data.

```sql
CREATE TABLE donors (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cnpj_cpf_hash    VARCHAR(64) UNIQUE,    -- SHA-256
  name             TEXT NOT NULL,
  entity_type      VARCHAR(20) CHECK (entity_type IN ('pessoa_fisica','pessoa_juridica')),
  sector_cnae      VARCHAR(20),           -- primary economic activity
  sector_group     VARCHAR(50),           -- 'agronegocio', 'financeiro', 'religioso', 'construtoras'...
  state_uf         CHAR(2),
  total_donated_brl NUMERIC(18,2)
);
```

---

### Junction / Relational Tables

#### `donor_links` — TSE financing records
```sql
CREATE TABLE donor_links (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  legislator_id  UUID REFERENCES legislators(id),
  donor_id       UUID REFERENCES donors(id),
  amount_brl     NUMERIC(18,2) NOT NULL,
  election_year  INTEGER NOT NULL,
  donation_type  VARCHAR(50),        -- 'campanha', 'partido'
  source_doc_ref TEXT,               -- TSE document reference
  UNIQUE(legislator_id, donor_id, election_year, donation_type)
);
```

#### `bill_constitution_mapping` — links bills to CF/88 articles
```sql
CREATE TABLE bill_constitution_mapping (
  bill_id              UUID REFERENCES bills(id),
  article_id           UUID REFERENCES constitution_articles(id),
  relationship         VARCHAR(20) CHECK (relationship IN ('compatible','conflicts','amends','regulates')),
  ai_confidence        FLOAT,           -- 0-1, how confident the model is
  reviewed_by_expert   BOOLEAN DEFAULT FALSE,
  expert_reviewer_id   UUID,
  expert_note          TEXT,
  expert_reviewed_at   TIMESTAMP,
  PRIMARY KEY (bill_id, article_id)
);
```

#### `legislator_themes` — aggregated thematic positions per legislator
```sql
CREATE TABLE legislator_themes (
  legislator_id      UUID REFERENCES legislators(id),
  theme_id           UUID REFERENCES themes(id),
  votes_favorable    INTEGER DEFAULT 0,
  votes_against      INTEGER DEFAULT 0,
  abstentions        INTEGER DEFAULT 0,
  absences           INTEGER DEFAULT 0,
  -- Derived score: positive = progressive on this theme, negative = conservative
  position_score     FLOAT CHECK (position_score BETWEEN -1 AND 1),
  last_updated       TIMESTAMP,
  PRIMARY KEY (legislator_id, theme_id)
);
```

#### `behavioral_clusters` — real coalitions derived from voting similarity
```sql
CREATE TABLE behavioral_clusters (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  label            VARCHAR(100),         -- e.g. 'Bancada Ruralista', 'Bloco Progressista'
  description      TEXT,
  dominant_themes  TEXT[],
  member_count     INTEGER,
  cohesion_score   FLOAT,               -- internal voting agreement rate
  algorithm        VARCHAR(50),         -- 'kmeans', 'hierarchical', 'spectral'
  algorithm_params JSONB,
  computed_at      TIMESTAMP
);
```

---

### Key Indexes

```sql
-- Most common query patterns
CREATE INDEX idx_votes_legislator ON votes(legislator_id);
CREATE INDEX idx_votes_bill ON votes(bill_id);
CREATE INDEX idx_votes_value ON votes(vote_value);
CREATE INDEX idx_bills_status ON bills(status);
CREATE INDEX idx_bills_tags ON bills USING GIN(theme_tags);
CREATE INDEX idx_legislators_cluster ON legislators(behavioral_cluster_id);
CREATE INDEX idx_donor_links_sector ON donors(sector_group);
```

---

## 2. API INTEGRATION LAYER

### Source APIs

| Source | Base URL | Auth | Update Freq |
|--------|----------|------|-------------|
| Câmara dos Deputados | `dadosabertos.camara.leg.br/api/v2` | None (public) | Daily |
| Senado Federal | `legis.senado.leg.br/dadosabertos/v2` | None (public) | Daily |
| TSE Eleições | `ce.tse.jus.br/dadosabertos` | None (public) | Per election |
| Diário Oficial | `in.gov.br/dados-abertos` | None | Daily |

### Sync Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      INGESTION PIPELINE                          │
│                                                                  │
│  Câmara API ──► CamaraClient ──►                                 │
│  Senado API ──► SenadoClient ──► Normalizer ──► DB Upsert       │
│  TSE Data   ──► TSELoader    ──►                                 │
│                                                                  │
│  Schedule: daily cron at 03:00 BRT (Brasília time)              │
└─────────────────────────────────────────────────────────────────┘
```

### Python Integration Client

```python
# vigilia/ingestion/camara_client.py

import httpx
import asyncio
from datetime import datetime, timedelta
from typing import AsyncGenerator
import logging

BASE_URL = "https://dadosabertos.camara.leg.br/api/v2"
logger = logging.getLogger(__name__)


class CamaraClient:
    """
    Async client for the Câmara dos Deputados open data API.
    Handles pagination, rate limiting, and error recovery.
    """

    def __init__(self, rate_limit_per_sec: float = 2.0):
        self.client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Accept": "application/json"},
            timeout=30.0,
        )
        self.rate_limit_per_sec = rate_limit_per_sec
        self._last_request = 0.0

    async def _get(self, endpoint: str, params: dict = None) -> dict:
        """Rate-limited GET with automatic retry on 429/503."""
        await self._throttle()
        for attempt in range(3):
            try:
                response = await self.client.get(endpoint, params=params or {})
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (429, 503) and attempt < 2:
                    await asyncio.sleep(2 ** attempt * 5)
                    continue
                raise
        raise RuntimeError(f"Failed after 3 attempts: {endpoint}")

    async def _throttle(self):
        import time
        elapsed = time.time() - self._last_request
        wait = (1.0 / self.rate_limit_per_sec) - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = time.time()

    async def get_legislators(self, legislature: int = 57) -> AsyncGenerator[dict, None]:
        """
        Fetch all deputies for a given legislature.
        Legislature 57 = 2023-2027 term.
        """
        page = 1
        while True:
            data = await self._get("/deputados", params={
                "idLegislatura": legislature,
                "itens": 100,
                "pagina": page,
                "ordem": "ASC",
                "ordenarPor": "nome"
            })

            items = data.get("dados", [])
            if not items:
                break

            for item in items:
                yield self._normalize_legislator(item)

            links = data.get("links", [])
            has_next = any(l.get("rel") == "next" for l in links)
            if not has_next:
                break
            page += 1

    async def get_legislator_detail(self, camara_id: int) -> dict:
        """Get full profile including declared assets, education, etc."""
        data = await self._get(f"/deputados/{camara_id}")
        return self._normalize_legislator_detail(data.get("dados", {}))

    async def get_votes_for_bill(self, camara_id: int) -> list[dict]:
        """
        Get all individual votes for a given bill (proposição).
        Returns list of {legislator_camara_id, vote_value, party_orientation}
        """
        data = await self._get(f"/proposicoes/{camara_id}/votacoes")
        votes = []
        for session_vote in data.get("dados", []):
            session_data = await self._get(
                f"/votacoes/{session_vote['id']}/votos"
            )
            for v in session_data.get("dados", []):
                votes.append({
                    "legislator_camara_id": v.get("deputado_", {}).get("id"),
                    "vote_value": self._normalize_vote(v.get("tipoVoto")),
                    "party_orientation": v.get("orientacaoVoto"),
                    "session_camara_id": session_vote["id"],
                    "voted_at": v.get("dataHoraVoto"),
                })
        return votes

    async def get_bills(
        self,
        since_date: datetime = None,
        bill_types: list[str] = None
    ) -> AsyncGenerator[dict, None]:
        """
        Stream bills, optionally filtered by date and type.
        bill_types: ['PL', 'PEC', 'MPV', 'PDL']
        """
        if since_date is None:
            since_date = datetime.now() - timedelta(days=30)
        if bill_types is None:
            bill_types = ["PL", "PEC", "MPV"]

        for bill_type in bill_types:
            page = 1
            while True:
                data = await self._get("/proposicoes", params={
                    "siglaTipo": bill_type,
                    "dataApresentacaoInicio": since_date.strftime("%Y-%m-%d"),
                    "itens": 100,
                    "pagina": page,
                })
                items = data.get("dados", [])
                if not items:
                    break
                for item in items:
                    yield self._normalize_bill(item)
                links = data.get("links", [])
                if not any(l.get("rel") == "next" for l in links):
                    break
                page += 1

    # ── Normalization helpers ──────────────────────────────────────

    def _normalize_legislator(self, raw: dict) -> dict:
        return {
            "camara_id": raw.get("id"),
            "name": raw.get("nome"),
            "display_name": raw.get("nomeCivil", raw.get("nome")),
            "chamber": "camara",
            "state_uf": raw.get("siglaUf"),
            "party_acronym": raw.get("siglaPartido"),
            "photo_url": raw.get("urlFoto"),
        }

    def _normalize_legislator_detail(self, raw: dict) -> dict:
        """Extended fields from /deputados/{id}"""
        base = self._normalize_legislator(raw)
        base.update({
            "education_level": raw.get("escolaridade"),
            "declared_assets_brl": self._parse_assets(raw),
            "cpf_hash": self._hash_cpf(raw.get("cpf", "")),
            "term_start": raw.get("dataNascimento"),  # using this as proxy; real term data in legislatura
        })
        return base

    def _normalize_bill(self, raw: dict) -> dict:
        return {
            "camara_id": raw.get("id"),
            "type": raw.get("siglaTipo"),
            "number": raw.get("numero"),
            "year": raw.get("ano"),
            "title": raw.get("ementa"),
            "summary_official": raw.get("ementa"),
            "status": raw.get("statusProposicao", {}).get("descricaoSituacao"),
            "presentation_date": raw.get("dataApresentacao"),
        }

    def _normalize_vote(self, tipo_voto: str) -> str:
        mapping = {
            "Sim": "sim",
            "Não": "não",
            "Abstenção": "abstencao",
            "Obstrução": "obstrucao",
            "Artigo 17": "ausente",
        }
        return mapping.get(tipo_voto, "ausente")

    def _parse_assets(self, raw: dict) -> float | None:
        # TSE data comes from a separate endpoint; placeholder
        return None

    def _hash_cpf(self, cpf: str) -> str:
        import hashlib
        clean = cpf.replace(".", "").replace("-", "").strip()
        return hashlib.sha256(clean.encode()).hexdigest() if clean else None

    async def close(self):
        await self.client.aclose()
```

```python
# vigilia/ingestion/sync_pipeline.py

import asyncio
from datetime import datetime, timedelta
from vigilia.ingestion.camara_client import CamaraClient
from vigilia.db import get_db_session
from vigilia.models import Legislator, Bill, Vote

async def sync_legislators():
    client = CamaraClient()
    db = get_db_session()
    try:
        async for leg_data in client.get_legislators(legislature=57):
            # Detail fetch for extended profile
            detail = await client.get_legislator_detail(leg_data["camara_id"])
            leg_data.update(detail)

            # Upsert by camara_id
            existing = db.query(Legislator).filter_by(
                camara_id=leg_data["camara_id"]
            ).first()

            if existing:
                for k, v in leg_data.items():
                    if v is not None:
                        setattr(existing, k, v)
            else:
                db.add(Legislator(**leg_data))

        db.commit()
        print(f"[sync_legislators] done at {datetime.now().isoformat()}")
    finally:
        await client.close()


async def sync_recent_bills(days_back: int = 7):
    client = CamaraClient()
    db = get_db_session()
    since = datetime.now() - timedelta(days=days_back)
    try:
        async for bill_data in client.get_bills(since_date=since):
            existing = db.query(Bill).filter_by(
                camara_id=bill_data["camara_id"]
            ).first()
            if existing:
                for k, v in bill_data.items():
                    if v is not None:
                        setattr(existing, k, v)
            else:
                db.add(Bill(**bill_data))
        db.commit()
    finally:
        await client.close()


async def sync_votes_for_bill(bill_camara_id: int):
    """
    Pull all individual votes for a given bill and store them.
    Run this after a bill reaches 'votação' status.
    """
    client = CamaraClient()
    db = get_db_session()
    try:
        bill = db.query(Bill).filter_by(camara_id=bill_camara_id).first()
        if not bill:
            raise ValueError(f"Bill {bill_camara_id} not found in DB")

        votes = await client.get_votes_for_bill(bill_camara_id)
        for v in votes:
            legislator = db.query(Legislator).filter_by(
                camara_id=v["legislator_camara_id"]
            ).first()
            if not legislator:
                continue  # deputy not in our DB yet; will be caught on next sync

            vote = Vote(
                legislator_id=legislator.id,
                bill_id=bill.id,
                vote_value=v["vote_value"],
                party_orientation=v["party_orientation"],
                voted_at=v["voted_at"],
            )
            # Compute derived flags
            vote.followed_party_line = (
                v["vote_value"] == v["party_orientation"]
                if v["party_orientation"] not in ("livre", None)
                else None
            )
            db.merge(vote)

        db.commit()
    finally:
        await client.close()


# Cron entry point
if __name__ == "__main__":
    async def main():
        print("Starting daily sync...")
        await sync_legislators()
        await sync_recent_bills(days_back=2)
        print("Sync complete.")

    asyncio.run(main())
```

---

## 3. CONSTITUTIONAL SCORING METHODOLOGY

### Conceptual Framework

The constitutional scoring system operates on two axes:

**Axis A — Bill Risk Score (0 to 1)**
> How likely is this bill to conflict with the CF/88, based on text analysis
> and structural comparison with constitutional provisions?
> 0 = no risk detected, 1 = near-certain conflict

**Axis B — Legislator Alignment Score (–1 to 1)**
> Across all bills they voted on that had a constitutional assessment,
> how often did a legislator vote for constitutionally-aligned outcomes?
> –1 = systematically votes to undermine constitutional provisions,
> +1 = consistently votes to protect or reinforce them

### Bill Risk Scoring Pipeline

```python
# vigilia/analysis/constitutional_scorer.py

import anthropic
from vigilia.db import get_db_session
from vigilia.models import Bill, ConstitutionArticle, BillConstitutionMapping

CONSTITUTION_SYSTEM_PROMPT = """
Você é um analista jurídico especializado na Constituição Federal do Brasil de 1988 (CF/88).
Sua função é avaliar se um projeto de lei (PL, PEC, MPV ou similar) apresenta riscos de 
inconstitucionalidade, com base exclusivamente no texto constitucional e na jurisprudência 
do STF.

Diretrizes:
- Fundamente sempre sua análise em artigos específicos da CF/88
- Distinga entre inconstitucionalidade formal (processo) e material (conteúdo)
- Considere precedentes do STF quando relevantes
- Seja objetivo e jurídico: não use posições políticas como fundamento
- Quando incerto, indique baixa confiança (< 0.5)

Responda APENAS em JSON válido, sem texto adicional.
"""

SCORING_PROMPT_TEMPLATE = """
Analise o seguinte projeto de lei quanto à sua constitucionalidade:

TIPO: {bill_type}
NÚMERO: {bill_number}/{bill_year}
EMENTA: {title}
TEXTO (se disponível): {text_excerpt}

Artigos constitucionais potencialmente relevantes para contexto:
{relevant_articles}

Responda em JSON com esta estrutura exata:
{{
  "risk_score": <float entre 0 e 1>,
  "risk_level": "<nenhum|baixo|médio|alto|crítico>",
  "formal_risk": <boolean>,
  "material_risk": <boolean>,
  "implicated_articles": [
    {{
      "article_ref": "<e.g. Art. 7, inciso XIII>",
      "relationship": "<compatible|conflicts|amends|regulates>",
      "reasoning": "<max 200 chars>",
      "confidence": <float 0-1>
    }}
  ],
  "summary_pt": "<explicação em português simples, máximo 300 chars>",
  "expert_review_needed": <boolean>,
  "confidence": <float 0-1>
}}
"""


class ConstitutionalScorer:

    def __init__(self):
        self.client = anthropic.Anthropic()
        self.db = get_db_session()

    def get_relevant_articles(self, bill_theme_tags: list[str]) -> str:
        """Fetch CF/88 articles relevant to a bill's themes."""
        articles = self.db.query(ConstitutionArticle).filter(
            ConstitutionArticle.theme_tags.overlap(bill_theme_tags)
        ).limit(10).all()

        if not articles:
            return "(nenhum artigo pré-mapeado para estes temas)"

        return "\n".join([
            f"• {a.article_ref}: {a.title or ''}\n  {a.text_full[:300]}..."
            for a in articles
        ])

    async def score_bill(self, bill: Bill) -> dict:
        """
        Run constitutional analysis on a bill.
        Returns structured scoring result.
        """
        relevant_articles = self.get_relevant_articles(
            bill.theme_tags or []
        )

        prompt = SCORING_PROMPT_TEMPLATE.format(
            bill_type=bill.type,
            bill_number=bill.number,
            bill_year=bill.year,
            title=bill.title,
            text_excerpt=(bill.full_text_url or "")[:2000],  # limit context
            relevant_articles=relevant_articles,
        )

        response = self.client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1500,
            system=CONSTITUTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )

        import json
        raw = response.content[0].text
        result = json.loads(raw)

        # Persist to DB
        bill.const_risk_score = result["risk_score"]

        for article_hit in result.get("implicated_articles", []):
            article = self.db.query(ConstitutionArticle).filter_by(
                article_ref=article_hit["article_ref"]
            ).first()
            if article:
                mapping = BillConstitutionMapping(
                    bill_id=bill.id,
                    article_id=article.id,
                    relationship=article_hit["relationship"],
                    ai_confidence=article_hit["confidence"],
                    reviewed_by_expert=False,
                )
                self.db.merge(mapping)

        self.db.commit()
        return result

    def compute_legislator_alignment(self, legislator_id: str) -> float:
        """
        Compute a legislator's constitutional alignment score.

        Logic:
        - For each vote they cast on a bill with const_risk_score > 0.5:
          * If they voted AGAINST a high-risk bill → +1 point
          * If they voted FOR a high-risk bill → -1 point
          * If they voted FOR a low-risk bill → +0.5 point
          * If they voted AGAINST a low-risk bill → -0.5 point
        - Normalize to [-1, 1]

        This is a first approximation. Calibration with expert review is required.
        """
        from vigilia.models import Vote, Bill

        votes = (
            self.db.query(Vote, Bill)
            .join(Bill, Vote.bill_id == Bill.id)
            .filter(Vote.legislator_id == legislator_id)
            .filter(Bill.const_risk_score.isnot(None))
            .all()
        )

        if not votes:
            return 0.0

        score = 0.0
        weight_total = 0.0

        for vote, bill in votes:
            risk = bill.const_risk_score
            weight = abs(risk - 0.5) * 2  # weight is higher for clearer cases
            weight_total += weight

            if risk > 0.5:
                # High-risk bill: voting against it is constitutionally aligned
                score += weight * (1 if vote.vote_value == "não" else -1)
            else:
                # Low-risk bill: voting for it is constitutionally aligned
                score += weight * (1 if vote.vote_value == "sim" else -0.5)

        normalized = score / weight_total if weight_total > 0 else 0.0
        return max(-1.0, min(1.0, normalized))
```

### Expert Review Workflow

AI scoring alone is insufficient for constitutional analysis. The pipeline includes
an expert review layer:

```
Bill submitted → AI scores it (confidence flagged)
       ↓
If confidence < 0.7 OR risk_score > 0.6:
       ↓
   expert_review_needed = True → queued for legal reviewer
       ↓
   Reviewer submits confirmed analysis via admin panel
       ↓
   reviewed_by_expert = True; expert_note populated
       ↓
   Public display shows "✓ Revisado por especialista"
```

**Expert panel composition (ideal)**:
- Constitutional law professors (from UERJ, USP, UnB)
- OAB (Brazilian Bar Association) members
- STF clerks / retired STF staff
- Partner NGOs: CONECTAS, Transparência Internacional Brasil

**How to attract volunteer reviewers**:
- Transparent methodology and open source codebase
- Attribution on the platform
- Partnership with academic institutions for research credit
- API access for researchers who contribute reviews

---

## 4. GOVERNANCE & SUSTAINABILITY

### Organizational Model

The strongest model for something like Vigília in the Brazilian context is a
**hybrid: independent non-profit tech lab** with institutional partnerships.

This avoids the three failure modes common in Brazilian civic tech:
1. NGO dependency on foreign grants (vulnerable to political shifts)
2. Government dependency (loses independence)
3. Commercial pressure (creates conflict of interest)

#### Recommended structure: Associação Civil

Register as an *associação sem fins lucrativos* under Brazilian civil law.
- Governed by a board (*conselho deliberativo*) with representatives from
  journalism, law, academia, and civil society
- Technical operations managed by a small paid staff
- Expert review network as volunteer contributors with governance rights

#### Editorial Independence Policy

Critical: establish a **firewall** between funding and editorial/analytical decisions.

- No donor can influence how their own legislators are scored
- Constitutional scoring methodology is publicly documented and peer-reviewed
- Any methodology change requires board approval and public consultation
- All code is open source (AGPL license)
- All data is open data (CC BY 4.0)

---

### Funding Model (Layered)

**Layer 1 — Foundation grants (years 1–2)**
Immediate target funders operating in Brazil:
- Open Society Foundations (Brazil program)
- Luminate Group (transparency/democracy)
- Instituto Clima e Sociedade (if environmental bills are in scope)
- MacArthur Foundation (democracy program)
- BNDES Garagem (if framed as civic tech startup)
- FAPESP/FAPERJ (if academic partner is primary applicant)

**Layer 2 — Institutional partnerships (year 2+)**
Revenue-neutral but provides legitimacy and resources:
- Agência Pública, The Intercept Brasil, Piauí: data partnership
  (they use Vigília data for reporting; contribute fact-checking capacity)
- Universities: UERJ, USP, Unicamp — research agreements that provide
  server infrastructure and RA labor
- OAB federal: institutional endorsement + volunteer legal reviewer network

**Layer 3 — Earned revenue (year 3+)**
Never from partisan sources. Acceptable:
- API access tiers for news organizations (freemium)
- Custom data exports for academic researchers
- Workshops/training for journalists on data literacy
- White-label dashboard for state-level assemblies (Alesp, ALERJ)

**Layer 4 — Individual donations**
Brazilian crowdfunding for civic causes is growing:
- Catarse or Benfeitoria campaigns
- Monthly donor community (subscribers pay what they can)
- Diaspora Brazilian community abroad (particularly Europe/US) often
  more willing to donate for democracy-related causes

---

### Risk Register

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Legal pressure from legislators | Medium | Legal partnership with OAB; clear methodology documentation |
| Platform capture by political group | Medium | Board composition rules; conflict of interest policy |
| API data quality degradation (Câmara changes API) | High | Abstract client layer; versioned endpoints; 30-day data cache |
| AI hallucination in constitutional scores | High | Mandatory expert review for high-risk flags; confidence threshold |
| Funding gap after initial grants | Medium | Diversified funding from day 1; build earned revenue early |
| LGPD compliance for donor data | Medium | Hash all CPF/CNPJ; publish privacy policy; DPO appointed |
| Disinformation about the platform | Medium | Radical transparency; open source; public methodology |

---

### Technical Sustainability

**Infrastructure** (low-cost path):
- Database: PostgreSQL on Railway or Supabase (free tier to start)
- API: FastAPI on Railway ($5/mo)
- Frontend: Next.js on Vercel (free tier)
- Scheduled sync: GitHub Actions cron (free)
- AI calls: Anthropic API (budget $200/mo for analysis; optimize with caching)

**Total infrastructure cost at MVP scale: ~$250–400/month**

**Scaling trigger**: when public traffic exceeds ~50k sessions/month,
migrate to dedicated VPS (Hetzner, ~$40/mo for 4-core/8GB).

**Data archival policy**:
- All legislative data archived independently of Câmara API
- Wayback Machine snapshot of all bills weekly
- Public data dumps released quarterly (CC BY 4.0)

---

### Phase Roadmap

```
Phase 1 — Foundation (months 1–4)
  □ Câmara API integration (legislators + bills + votes)
  □ PostgreSQL schema deployed
  □ Basic Next.js dashboard: deputy profiles, bill tracker, vote filter
  □ Public launch with current legislature data
  □ Open source on GitHub

Phase 2 — Intelligence (months 5–8)
  □ NLP thematic tagging pipeline
  □ Voting similarity clustering (behavioral coalitions)
  □ TSE donor data integration + donor-vote flag
  □ Constitutional scoring v1 (AI only)
  □ Expert review workflow

Phase 3 — AI + UX (months 9–12)
  □ Farol assistant (RAG on full dataset, Portuguese)
  □ Alert subscriptions (follow a deputy or a theme)
  □ Mobile-optimized views (Brazil is mobile-first)
  □ Press/researcher API (documented, versioned)
  □ Senado integration

Phase 4 — Ecosystem (year 2+)
  □ State assembly data (Alesp, ALERJ)
  □ Municipal chambers (Câmara Municipal SP, RJ)
  □ Open API for third-party integrations
  □ Partner journalism dashboard
```

---

*Document version: 0.1 — April 2026*
*License: CC BY 4.0 — free to use, adapt, and build upon with attribution*
