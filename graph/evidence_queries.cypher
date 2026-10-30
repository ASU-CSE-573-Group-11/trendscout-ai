// Claims supported by one source record.
MATCH (record:SourceRecord)-[:SUPPORTS]->(claim:Claim)
RETURN claim, record
ORDER BY claim.observed_at DESC;

// Claims for one startup in a selected evidence state.
MATCH (record:SourceRecord)-[:ABOUT]->(startup:Startup),
      (record)-[:SUPPORTS]->(claim:Claim)
WHERE startup.company_id = $company_id
  AND claim.state = $state
RETURN claim, record
ORDER BY claim.observed_at DESC;

// Independent origins supporting each claim.
MATCH (record:SourceRecord)-[:SUPPORTS]->(claim:Claim)
RETURN claim.claim_id AS claim_id,
       count(DISTINCT record.origin_cluster_id) AS independent_origins,
       collect(DISTINCT record.record_id) AS supporting_records;

// Evidence path for a temporal claim review.
MATCH path = (startup:Startup)<-[:ABOUT]-(record:SourceRecord)-[:SUPPORTS]->(claim:Claim)
WHERE startup.company_id = $company_id
  AND claim.observed_at >= $observed_from
  AND claim.observed_at < $observed_to
RETURN path
ORDER BY claim.observed_at;
