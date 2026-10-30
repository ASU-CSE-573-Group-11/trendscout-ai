// Temporal multi-hop evidence path:
// startup -> source record -> claim, restricted to an observation window.
MATCH path = (startup:Startup)<-[:ABOUT]-(record:SourceRecord)-[:SUPPORTS]->(claim:Claim)
WHERE startup.company_id = $company_id
  AND record.observed_at >= $observed_from
  AND record.observed_at < $observed_to
RETURN path
ORDER BY record.observed_at, claim.claim_id;

// Require independent origins before treating a claim as corroborated.
MATCH (startup:Startup)<-[:ABOUT]-(record:SourceRecord)-[:SUPPORTS]->(claim:Claim)
WHERE startup.company_id = $company_id
  AND claim.state = "corroborated"
WITH claim, collect(DISTINCT record.origin_cluster_id) AS origins
WHERE size(origins) >= $minimum_independent_origins
RETURN claim.claim_id AS claim_id, origins;

// Return the latest evidence state while retaining the supporting path.
MATCH path = (startup:Startup)<-[:ABOUT]-(record:SourceRecord)-[:SUPPORTS]->(claim:Claim)
WHERE startup.company_id = $company_id
WITH claim, path
ORDER BY claim.state_changed_at DESC
RETURN claim, path;
