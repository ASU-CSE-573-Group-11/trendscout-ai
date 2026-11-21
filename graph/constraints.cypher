// Run once against the TrendScout Neo4j database before importing records.
CREATE CONSTRAINT source_record_id IF NOT EXISTS
FOR (record:SourceRecord)
REQUIRE record.record_id IS UNIQUE;

CREATE CONSTRAINT startup_company_id IF NOT EXISTS
FOR (startup:Startup)
REQUIRE startup.company_id IS UNIQUE;

CREATE CONSTRAINT publisher_name IF NOT EXISTS
FOR (publisher:Publisher)
REQUIRE publisher.name IS UNIQUE;

CREATE CONSTRAINT origin_cluster_id IF NOT EXISTS
FOR (origin:OriginCluster)
REQUIRE origin.origin_cluster_id IS UNIQUE;

CREATE CONSTRAINT claim_id IF NOT EXISTS
FOR (claim:Claim)
REQUIRE claim.claim_id IS UNIQUE;

CREATE CONSTRAINT investor_name IF NOT EXISTS
FOR (investor:Investor)
REQUIRE investor.name IS UNIQUE;

CREATE CONSTRAINT funding_round_id IF NOT EXISTS
FOR (round:FundingRound)
REQUIRE round.round_id IS UNIQUE;

CREATE CONSTRAINT job_posting_id IF NOT EXISTS
FOR (posting:JobPosting)
REQUIRE posting.job_posting_id IS UNIQUE;

CREATE CONSTRAINT repository_id IF NOT EXISTS
FOR (repository:Repository)
REQUIRE repository.repository_id IS UNIQUE;

CREATE CONSTRAINT skill_name IF NOT EXISTS
FOR (skill:Skill)
REQUIRE skill.name IS UNIQUE;

CREATE CONSTRAINT technology_name IF NOT EXISTS
FOR (technology:Technology)
REQUIRE technology.name IS UNIQUE;

CREATE INDEX source_record_observed_at IF NOT EXISTS
FOR (record:SourceRecord)
ON (record.observed_at);

CREATE INDEX source_record_company_id IF NOT EXISTS
FOR (record:SourceRecord)
ON (record.company_id);

CREATE INDEX job_posting_observed_at IF NOT EXISTS
FOR (posting:JobPosting)
ON (posting.observed_at);

CREATE INDEX funding_round_observed_at IF NOT EXISTS
FOR (round:FundingRound)
ON (round.observed_at);
