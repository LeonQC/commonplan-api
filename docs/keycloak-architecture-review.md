# Keycloak responsibility review

## Decision

Zhitong will keep control of its own Auth Service. Keycloak is used as a responsibility and boundary
reference, not as a runtime dependency.

The useful architectural lesson is that the identity/token authority and the resource server are
different security roles. The Auth Service owns credentials, identity-provider federation, token
issuance, refresh/revocation, signing keys, and eventually recovery/MFA/admin workflows. Business API
validates access tokens using public keys and owns application profiles, team membership, projects,
issues, and resource authorization.

See [Auth Service separation plan](auth-service-plan.md) for the implemented design, security
invariants, cutover process, and roadmap toward broader identity-platform responsibilities.

## Responsibility comparison

| Concern | Zhitong implementation now | Keycloak-style mature capability | Status |
| --- | --- | --- | --- |
| Identity store | Separate Auth PostgreSQL database | Realm-owned identity store | Implemented boundary |
| Password and Google login | Auth Service endpoints | Login flows and identity brokering | Implemented first-party flows |
| Access tokens | RS256, `typ=at+jwt`, issuer/audience validation | Asymmetric realm access tokens | Implemented resource-token model |
| Public signing keys | JWKS endpoint and Business API cache | OIDC/JWKS key publication | Implemented JWKS; rotation pending |
| Refresh lifecycle | Opaque rotating families with replay revocation | Server-side user/client sessions | Implemented core rotation |
| API enforcement | Protected FastAPI router plus policy dependencies | Resource-server adapter/policies | Implemented fail-closed baseline |
| Product sessions | Zhitong Postgres plus Redis cache | Outside identity provider | Correctly remains separate |
| Recovery and verification | Not present | Built-in email actions | Roadmap |
| MFA and security admin | Not present | Built-in flows and console | Roadmap |
| Standard OIDC provider | Not advertised | Discovery, authorize/token/userinfo | Roadmap; do not claim conformance |

Owning the service provides schema and UX control, but also transfers security maintenance and
operational responsibility to Zhitong. New protocol surface should be added only with threat modeling,
interoperability tests, monitoring, and a concrete product requirement.
