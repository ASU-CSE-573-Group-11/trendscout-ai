// Source records for one startup, newest observations first.
MATCH (record:SourceRecord)-[:ABOUT]->(startup:Startup {company_id: $company_id})
RETURN record, startup
ORDER BY record.observed_at DESC;

// Independent documentary origins for one startup.
MATCH (record:SourceRecord)-[:ABOUT]->(startup:Startup {company_id: $company_id})
RETURN startup.company_id AS company_id,
       count(DISTINCT record.origin_cluster_id) AS independent_origins;

// Evidence observed inside a requested time window.
MATCH (record:SourceRecord)-[:ABOUT]->(startup:Startup)
WHERE record.observed_at >= $observed_from
  AND record.observed_at < $observed_to
RETURN startup.company_id AS company_id, record
ORDER BY record.observed_at;

// Provenance path from a startup to its source publisher.
MATCH path = (startup:Startup)<-[:ABOUT]-(record:SourceRecord)-[:PUBLISHED_BY]->(publisher:Publisher)
WHERE startup.company_id = $company_id
RETURN path;
