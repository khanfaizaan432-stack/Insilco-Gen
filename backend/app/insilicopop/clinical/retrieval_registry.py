from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.insilicopop.clinical.integrated_analysis_models import (
    CandidateBinding,
    CorrectionRetractionState,
    DatabaseEvidenceRecord,
    EvidenceLifecycleState,
    EvidenceRole,
    FreshnessState,
    FrozenRetrievalFixture,
    PaperEvidenceRecord,
    RetrievalCacheStatus,
    RetrievalEvent,
    RetrievalFailureState,
    SourceAvailability,
    TypedRetrievalQuery,
    canonical_json,
    sha256_hex,
)


RETRIEVAL_REGISTRY_VERSION = "insilicopop-retrieval-registry-0.38.0"
PUBMED_ADAPTER_VERSION = "insilicopop-pubmed-eutils-0.38.0"
CLINVAR_ADAPTER_VERSION = "insilicopop-clinvar-eutils-0.38.0"
ENSEMBL_ADAPTER_VERSION = "insilicopop-ensembl-vep-0.38.0"


class RetrievalRegistryDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    official_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    adapter_version: str
    typed_query_schema: str
    normalized_result_schema: str
    timeout_seconds: int = Field(ge=1, le=120)
    response_size_limit_bytes: int = Field(ge=1024, le=50_000_000)
    redirect_policy: str
    retry_policy: str
    cache_policy: str
    source_release: str
    parser_version: str
    availability: SourceAvailability
    credential_requirements: str
    correction_retraction_support: bool
    allowed_content_types: tuple[str, ...]


RETRIEVAL_REGISTRY: tuple[RetrievalRegistryDefinition, ...] = (
    RetrievalRegistryDefinition(
        source_id="pubmed",
        official_hosts=("eutils.ncbi.nlm.nih.gov",),
        allowed_path_prefixes=("/entrez/eutils/",),
        adapter_version=PUBMED_ADAPTER_VERSION,
        typed_query_schema="TypedRetrievalQuery(pubmed)",
        normalized_result_schema="PaperEvidenceRecord",
        timeout_seconds=20,
        response_size_limit_bytes=4_000_000,
        redirect_policy="same-host-only",
        retry_policy="bounded-429-5xx-exponential",
        cache_policy="memory-only-digest-cache",
        source_release="NCBI E-utilities",
        parser_version="pubmed-eutils-parser-0.38.0",
        availability=SourceAvailability.AVAILABLE,
        credential_requirements="none for bounded public synthetic smoke queries",
        correction_retraction_support=True,
        allowed_content_types=("application/json", "application/xml", "text/xml"),
    ),
    RetrievalRegistryDefinition(
        source_id="clinvar",
        official_hosts=("eutils.ncbi.nlm.nih.gov",),
        allowed_path_prefixes=("/entrez/eutils/",),
        adapter_version=CLINVAR_ADAPTER_VERSION,
        typed_query_schema="TypedRetrievalQuery(clinvar)",
        normalized_result_schema="DatabaseEvidenceRecord",
        timeout_seconds=20,
        response_size_limit_bytes=4_000_000,
        redirect_policy="same-host-only",
        retry_policy="bounded-429-5xx-exponential",
        cache_policy="memory-only-digest-cache",
        source_release="NCBI ClinVar E-utilities",
        parser_version="clinvar-eutils-parser-0.38.0",
        availability=SourceAvailability.AVAILABLE,
        credential_requirements="none for bounded public synthetic smoke queries",
        correction_retraction_support=False,
        allowed_content_types=("application/json", "application/xml", "text/xml"),
    ),
    RetrievalRegistryDefinition(
        source_id="ensembl",
        official_hosts=("rest.ensembl.org",),
        allowed_path_prefixes=("/vep/",),
        adapter_version=ENSEMBL_ADAPTER_VERSION,
        typed_query_schema="TypedRetrievalQuery(ensembl)",
        normalized_result_schema="DatabaseEvidenceRecord",
        timeout_seconds=20,
        response_size_limit_bytes=4_000_000,
        redirect_policy="same-host-only",
        retry_policy="bounded-429-5xx-exponential",
        cache_policy="memory-only-digest-cache",
        source_release="Ensembl REST",
        parser_version="ensembl-vep-parser-0.38.0",
        availability=SourceAvailability.AVAILABLE,
        credential_requirements="none for bounded public synthetic smoke queries",
        correction_retraction_support=False,
        allowed_content_types=("application/json",),
    ),
    RetrievalRegistryDefinition(
        source_id="clingen",
        official_hosts=("search.clinicalgenome.org",),
        allowed_path_prefixes=("/kb/downloads",),
        adapter_version="insilicopop-clingen-snapshot-0.38.0",
        typed_query_schema="PinnedManualSnapshotReference",
        normalized_result_schema="DatabaseEvidenceRecord",
        timeout_seconds=20,
        response_size_limit_bytes=20_000_000,
        redirect_policy="manual-verified-snapshot-only",
        retry_policy="none",
        cache_policy="hashed-supplied-snapshot",
        source_release="ClinGen downloads",
        parser_version="clingen-snapshot-parser-0.38.0",
        availability=SourceAvailability.MANUAL_VERIFIED_ONLY,
        credential_requirements="manual verified snapshot",
        correction_retraction_support=False,
        allowed_content_types=("text/csv", "text/tab-separated-values", "application/octet-stream"),
    ),
    RetrievalRegistryDefinition(
        source_id="gnomad",
        official_hosts=(),
        allowed_path_prefixes=(),
        adapter_version="insilicopop-gnomad-unavailable-0.38.0",
        typed_query_schema="disabled",
        normalized_result_schema="DatabaseEvidenceRecord",
        timeout_seconds=1,
        response_size_limit_bytes=1024,
        redirect_policy="disabled",
        retry_policy="none",
        cache_policy="none",
        source_release="not activated",
        parser_version="none",
        availability=SourceAvailability.UNAVAILABLE,
        credential_requirements="not applicable",
        correction_retraction_support=False,
        allowed_content_types=(),
    ),
    RetrievalRegistryDefinition(
        source_id="indigenomes",
        official_hosts=("clingen.igib.res.in",),
        allowed_path_prefixes=("/indigen/",),
        adapter_version="insilicopop-indigenomes-manual-0.38.0",
        typed_query_schema="VerifiedSuppliedFrequencyRecord",
        normalized_result_schema="DatabaseEvidenceRecord",
        timeout_seconds=1,
        response_size_limit_bytes=1024,
        redirect_policy="disabled",
        retry_policy="none",
        cache_policy="hashed-supplied-snapshot",
        source_release="manual verified snapshot only",
        parser_version="indigenomes-manual-parser-0.38.0",
        availability=SourceAvailability.MANUAL_VERIFIED_ONLY,
        credential_requirements="manual verified snapshot",
        correction_retraction_support=False,
        allowed_content_types=(),
    ),
    RetrievalRegistryDefinition(
        source_id="genomeindia_ibdc",
        official_hosts=("ibdc.dbt.gov.in", "genomeindia.in"),
        allowed_path_prefixes=("/",),
        adapter_version="insilicopop-genomeindia-managed-0.38.0",
        typed_query_schema="managed-access-reference",
        normalized_result_schema="DatabaseEvidenceRecord",
        timeout_seconds=1,
        response_size_limit_bytes=1024,
        redirect_policy="disabled",
        retry_policy="none",
        cache_policy="none",
        source_release="managed access",
        parser_version="none",
        availability=SourceAvailability.MANAGED_ACCESS,
        credential_requirements="IBDC/FeED/BIOTECH-PRIDE authorization",
        correction_retraction_support=False,
        allowed_content_types=(),
    ),
)


def registered_retrieval_adapters() -> tuple[RetrievalRegistryDefinition, ...]:
    return RETRIEVAL_REGISTRY


def get_retrieval_definition(source_id: str) -> RetrievalRegistryDefinition:
    for definition in RETRIEVAL_REGISTRY:
        if definition.source_id == source_id:
            return definition
    raise KeyError(f"unknown retrieval source: {source_id}")


def validate_allowlisted_url(url: str, source_id: str) -> str:
    definition = get_retrieval_definition(source_id)
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError("retrieval URL must use HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("retrieval URL cannot contain credentials")
    if parsed.fragment:
        raise ValueError("retrieval URL cannot contain a fragment")
    if parsed.port not in (None, 443):
        raise ValueError("retrieval URL must use the default HTTPS port")
    hostname = (parsed.hostname or "").casefold()
    if not hostname or hostname not in {item.casefold() for item in definition.official_hosts}:
        raise ValueError("retrieval URL host is not allowlisted for the adapter")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
        raise ValueError("private, loopback, link-local and reserved destinations are blocked")
    if not any(parsed.path.startswith(prefix) for prefix in definition.allowed_path_prefixes):
        raise ValueError("retrieval URL path is not allowlisted for the adapter")
    return urllib.parse.urlunsplit(("https", hostname, parsed.path, parsed.query, ""))


def validate_redirect(url: str, source_id: str, original_url: str) -> str:
    validated = validate_allowlisted_url(url, source_id)
    original = urllib.parse.urlsplit(original_url)
    current = urllib.parse.urlsplit(validated)
    if current.hostname != original.hostname:
        raise ValueError("retrieval redirect left the original allowlisted host")
    return validated


def validate_response(
    body: bytes,
    *,
    source_id: str,
    content_type: str,
    content_encoding: str | None = None,
) -> bytes:
    definition = get_retrieval_definition(source_id)
    if len(body) > definition.response_size_limit_bytes:
        raise ValueError("retrieval response exceeds the adapter response-size limit")
    normalized_content_type = content_type.split(";", 1)[0].strip().casefold()
    if normalized_content_type not in {item.casefold() for item in definition.allowed_content_types}:
        raise ValueError("retrieval response content type is not allowlisted")
    if content_encoding and content_encoding.casefold() not in {"identity", ""}:
        raise ValueError("compressed retrieval responses are disabled to prevent decompression bombs")
    if b"\x00" in body:
        raise ValueError("binary retrieval response is not accepted by the typed parser")
    return body


@dataclass(frozen=True, slots=True)
class TransportResponse:
    url: str
    body: bytes
    content_type: str
    status_code: int = 200
    headers: Mapping[str, str] | None = None


class FixtureTransport:
    """Deterministic transport. It has no network fallback."""

    def __init__(self, responses: Mapping[str, TransportResponse] | None = None) -> None:
        self._responses = dict(responses or {})
        self.requested_urls: list[str] = []

    def add(self, url: str, response: TransportResponse) -> None:
        self._responses[url] = response

    def get(self, url: str, *, source_id: str, timeout_seconds: int) -> TransportResponse:
        del timeout_seconds
        validated = validate_allowlisted_url(url, source_id)
        self.requested_urls.append(validated)
        response = self._responses.get(validated) or self._responses.get(url)
        if response is None:
            raise RetrievalUnavailable(f"no frozen fixture response for {validated}")
        if response.status_code >= 400:
            raise RetrievalUnavailable(f"fixture returned HTTP {response.status_code}")
        validate_response(response.body, source_id=source_id, content_type=response.content_type)
        return response


class UrllibTransport:
    """Read-only HTTPS transport with a fixed header set and bounded redirects."""

    def __init__(self, *, user_agent: str = "InSilicoPop/0.38 controlled-retrieval") -> None:
        self.user_agent = user_agent
        self.requested_urls: list[str] = []

    def get(self, url: str, *, source_id: str, timeout_seconds: int) -> TransportResponse:
        validated = validate_allowlisted_url(url, source_id)
        self.requested_urls.append(validated)
        request = urllib.request.Request(
            validated,
            headers={"Accept": ", ".join(get_retrieval_definition(source_id).allowed_content_types), "User-Agent": self.user_agent},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                final_url = response.geturl()
                validate_redirect(final_url, source_id, validated)
                body = response.read(get_retrieval_definition(source_id).response_size_limit_bytes + 1)
                content_type = response.headers.get("Content-Type", "")
                content_encoding = response.headers.get("Content-Encoding")
                validate_response(
                    body,
                    source_id=source_id,
                    content_type=content_type,
                    content_encoding=content_encoding,
                )
                return TransportResponse(
                    url=final_url,
                    body=body,
                    content_type=content_type.split(";", 1)[0].strip(),
                    status_code=getattr(response, "status", 200),
                    headers={key: value for key, value in response.headers.items() if key.casefold() in {"content-type", "content-encoding"}},
                )
        except urllib.error.HTTPError as exc:
            raise RetrievalUnavailable(f"official endpoint returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RetrievalUnavailable("official endpoint was unavailable or timed out") from exc


class RetrievalUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    response: TransportResponse
    stored_at: float
    ttl_seconds: float


class RetrievalCache:
    def __init__(self, *, clock: Callable[[], float] | None = None, ttl_seconds: float = 3600.0) -> None:
        self._clock = clock or time.time
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, _CacheEntry] = {}

    def get(self, key: str) -> tuple[TransportResponse | None, RetrievalCacheStatus]:
        entry = self._entries.get(key)
        if entry is None:
            return None, RetrievalCacheStatus.MISS
        if self._clock() - entry.stored_at > entry.ttl_seconds:
            return None, RetrievalCacheStatus.EXPIRED
        return entry.response, RetrievalCacheStatus.HIT

    def put(self, key: str, response: TransportResponse) -> None:
        self._entries[key] = _CacheEntry(response, self._clock(), self._ttl_seconds)

    def clear(self) -> None:
        self._entries.clear()


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    event: RetrievalEvent
    papers: tuple[PaperEvidenceRecord, ...] = ()
    database_records: tuple[DatabaseEvidenceRecord, ...] = ()
    fixture_replay: bool = False


class ControlledRetrievalService:
    def __init__(
        self,
        *,
        transport: FixtureTransport | UrllibTransport | None = None,
        cache: RetrievalCache | None = None,
        allow_live: bool = False,
        human_authorized: bool = False,
        clock: Callable[[], float] | None = None,
        timestamp: Callable[[], str] | None = None,
    ) -> None:
        self.allow_live = allow_live
        self.human_authorized = human_authorized
        self.transport = transport or (UrllibTransport() if allow_live and human_authorized else FixtureTransport())
        self.cache = cache or RetrievalCache(clock=clock)
        self._clock = clock or time.time
        self._timestamp = timestamp or (lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))

    def retrieve(
        self,
        query: TypedRetrievalQuery,
        *,
        frozen_fixture: FrozenRetrievalFixture | None = None,
    ) -> RetrievalResult:
        definition = get_retrieval_definition(query.source_id)
        signature = canonical_json(query.model_dump(mode="json"))
        key = f"{query.source_id}:{hashlib.sha256(signature.encode('utf-8')).hexdigest()}"
        fixture_replay = frozen_fixture is not None
        cache_status = RetrievalCacheStatus.NOT_CACHED
        response: TransportResponse | None = None
        failure_state = RetrievalFailureState.NONE
        failure_reason: str | None = None
        if frozen_fixture is not None:
            if frozen_fixture.source_id != query.source_id or frozen_fixture.request_signature != signature:
                raise ValueError("frozen retrieval fixture does not match the typed retrieval query")
            response = TransportResponse(
                url=self._fixture_url(query),
                body=frozen_fixture.response_body.encode("utf-8"),
                content_type=frozen_fixture.content_type,
                status_code=200,
            )
            validate_response(response.body, source_id=query.source_id, content_type=response.content_type)
            cache_status = RetrievalCacheStatus.REPLAY
            source_release = frozen_fixture.source_release
            retrieval_timestamp = frozen_fixture.recorded_at
        elif not (self.allow_live and self.human_authorized):
            failure_state = RetrievalFailureState.BLOCKED
            failure_reason = "live retrieval requires an explicit human authorization checkpoint"
            source_release = definition.source_release
            retrieval_timestamp = self._timestamp()
        else:
            response, cache_status = self.cache.get(key)
            source_release = definition.source_release
            retrieval_timestamp = self._timestamp()
            if response is None:
                try:
                    response = self._retrieve_live(query)
                    self.cache.put(key, response)
                    cache_status = RetrievalCacheStatus.MISS
                except RetrievalUnavailable as exc:
                    failure_state = RetrievalFailureState.UNAVAILABLE
                    failure_reason = str(exc)

        papers: tuple[PaperEvidenceRecord, ...] = ()
        database_records: tuple[DatabaseEvidenceRecord, ...] = ()
        raw_digest = sha256_hex(response.body) if response is not None else None
        normalized_digest: str | None = None
        record_ids: tuple[str, ...] = ()
        correction_status = CorrectionRetractionState.UNKNOWN
        lifecycle = EvidenceLifecycleState.QUARANTINED if failure_state != RetrievalFailureState.NONE else EvidenceLifecycleState.ELIGIBLE
        if response is not None and failure_state == RetrievalFailureState.NONE:
            try:
                papers, database_records = self._parse_response(query, response.body, raw_digest or "", retrieval_timestamp, source_release)
                normalized_items = [item.model_dump(mode="json") for item in papers + database_records]
                normalized_digest = sha256_hex(normalized_items)
                record_ids = tuple(item.evidence_id for item in papers + database_records)
                if any(getattr(item, "correction_retraction_status", CorrectionRetractionState.NONE) != CorrectionRetractionState.NONE for item in papers):
                    correction_status = next(item.correction_retraction_status for item in papers if item.correction_retraction_status != CorrectionRetractionState.NONE)
            except (ValueError, json.JSONDecodeError, KeyError, TypeError) as exc:
                failure_state = RetrievalFailureState.QUARANTINED
                failure_reason = f"typed parser rejected response: {exc}"
                lifecycle = EvidenceLifecycleState.QUARANTINED
        event_id = "retrieval-" + hashlib.sha256((signature + (raw_digest or "") + query.source_id).encode("utf-8")).hexdigest()[:24]
        event = RetrievalEvent(
            event_id=event_id,
            typed_query=query,
            source_id=query.source_id,
            source_release=source_release,
            retrieval_timestamp=retrieval_timestamp,
            adapter_version=definition.adapter_version,
            raw_response_sha256=raw_digest,
            normalized_record_identity_sha256=normalized_digest,
            cache_status=cache_status,
            freshness=FreshnessState.FRESH if response is not None and failure_state == RetrievalFailureState.NONE else FreshnessState.UNKNOWN,
            correction_retraction_status=correction_status,
            failure_state=failure_state,
            failure_or_quarantine_reason=failure_reason,
            evidence_lifecycle_state=lifecycle,
            candidate_binding=query.candidate_binding,
            record_ids=record_ids,
        )
        return RetrievalResult(source_id=query.source_id, event=event, papers=papers, database_records=database_records, fixture_replay=fixture_replay)

    def retrieve_many(
        self,
        queries: Iterable[TypedRetrievalQuery],
        *,
        frozen_fixtures: Iterable[FrozenRetrievalFixture] = (),
    ) -> tuple[RetrievalResult, ...]:
        fixtures = {item.request_signature: item for item in frozen_fixtures}
        return tuple(self.retrieve(query, frozen_fixture=fixtures.get(canonical_json(query.model_dump(mode="json")))) for query in queries)

    def _fixture_url(self, query: TypedRetrievalQuery) -> str:
        if query.source_id == "ensembl":
            identifier = query.rsid or query.variant_identifier or query.hgvs
            if not identifier:
                identifier = "unknown"
            return f"https://rest.ensembl.org/vep/human/id/{urllib.parse.quote(identifier, safe='') }"
        return f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/{query.source_id}.fcgi"

    def _retrieve_live(self, query: TypedRetrievalQuery) -> TransportResponse:
        definition = get_retrieval_definition(query.source_id)
        if query.source_id == "ensembl":
            identifier = query.rsid or query.variant_identifier or query.hgvs
            if not identifier or not re.fullmatch(r"[A-Za-z0-9_.:*+\->]+", identifier):
                raise RetrievalUnavailable("Ensembl VEP requires a typed public variant identifier")
            url = f"https://rest.ensembl.org/vep/human/id/{urllib.parse.quote(identifier, safe='') }"
            return self.transport.get(validate_allowlisted_url(url, "ensembl"), source_id="ensembl", timeout_seconds=definition.timeout_seconds)
        term_parts: list[str] = []
        if query.rsid:
            term_parts.append(query.rsid)
        elif query.hgvs or query.variant_identifier:
            term_parts.append(query.hgvs or query.variant_identifier or "")
        if query.gene:
            term_parts.append(f"{query.gene}[Gene Name]")
        term_parts.extend(query.condition_terms[:3])
        term = " AND ".join(item for item in term_parts if item)
        if not term or len(term) > 500:
            raise RetrievalUnavailable("NCBI query must contain a bounded typed variant or gene term")
        esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(
            {"db": query.source_id, "retmode": "json", "retmax": "5", "term": term},
            quote_via=urllib.parse.quote,
        )
        search_response = self.transport.get(esearch_url, source_id=query.source_id, timeout_seconds=definition.timeout_seconds)
        ids = parse_esearch_ids(search_response.body)
        if not ids:
            return search_response
        summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?" + urllib.parse.urlencode(
            {"db": query.source_id, "retmode": "json", "id": ",".join(ids)},
            quote_via=urllib.parse.quote,
        )
        summary_response = self.transport.get(summary_url, source_id=query.source_id, timeout_seconds=definition.timeout_seconds)
        # The ESummary response is the bounded normalized-record source. The
        # preceding ESearch IDs are represented in the typed query/event, so
        # raw ESearch XML/JSON is not persisted or concatenated into a parser
        # payload.
        return summary_response

    def _parse_response(
        self,
        query: TypedRetrievalQuery,
        body: bytes,
        raw_digest: str,
        timestamp: str,
        source_release: str,
    ) -> tuple[tuple[PaperEvidenceRecord, ...], tuple[DatabaseEvidenceRecord, ...]]:
        text = body.decode("utf-8")
        if query.source_id == "pubmed":
            return parse_pubmed_records(text, raw_digest=raw_digest, timestamp=timestamp, source_release=source_release, candidate_binding=query.candidate_binding)
        if query.source_id == "clinvar":
            return (), parse_clinvar_records(text, raw_digest=raw_digest, timestamp=timestamp, source_release=source_release, candidate_binding=query.candidate_binding)
        if query.source_id == "ensembl":
            return (), parse_ensembl_records(text, raw_digest=raw_digest, timestamp=timestamp, source_release=source_release, candidate_binding=query.candidate_binding)
        raise ValueError(f"source {query.source_id} does not have an operational parser")


def parse_esearch_ids(body: bytes | str) -> list[str]:
    payload = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    result = payload.get("esearchresult", {})
    ids = result.get("idlist", [])
    if not isinstance(ids, list):
        raise ValueError("NCBI esearch idlist is not a list")
    return [str(item) for item in ids if re.fullmatch(r"\d+", str(item))][:5]


def _normalized_identity(payload: dict[str, Any]) -> str:
    return sha256_hex(payload)


def _paper_payload(item: dict[str, Any], *, raw_digest: str, timestamp: str, source_release: str, candidate_binding: CandidateBinding | None) -> PaperEvidenceRecord:
    payload = dict(item)
    pmid = str(payload.pop("pmid"))
    payload.setdefault("evidence_id", f"paper-pmid-{pmid}")
    payload["pmid"] = pmid
    payload.setdefault("source_id", "pubmed")
    payload.setdefault("authors_summary", ())
    payload.setdefault("publication_type", ())
    payload.setdefault("official_pubmed_url", f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
    payload.setdefault("official_pmc_url", None)
    payload.setdefault("abstract_available", False)
    payload.setdefault("reusable_full_text_status", "not_assessed")
    publication_types = {str(item).casefold() for item in payload.get("publication_type", ())}
    if "retracted publication" in publication_types:
        payload.setdefault("correction_retraction_status", CorrectionRetractionState.RETRACTED.value)
        payload.setdefault("evidence_lifecycle_state", EvidenceLifecycleState.EXCLUDED.value)
        payload.setdefault("evidence_role", EvidenceRole.CONTEXT_ONLY.value)
    elif "published erratum" in publication_types or "corrected and republished article" in publication_types:
        payload.setdefault("correction_retraction_status", CorrectionRetractionState.CORRECTED.value)
    else:
        payload.setdefault("correction_retraction_status", CorrectionRetractionState.NONE.value)
    payload.setdefault("retrieval_timestamp", timestamp)
    payload.setdefault("source_api_version", source_release)
    payload.setdefault("adapter_version", PUBMED_ADAPTER_VERSION)
    payload["raw_response_sha256"] = raw_digest
    payload["candidate_binding"] = candidate_binding.model_dump(mode="json") if candidate_binding else payload.get("candidate_binding")
    payload.setdefault("evidence_role", EvidenceRole.UNRESOLVED.value)
    payload.setdefault("evidence_lifecycle_state", EvidenceLifecycleState.ELIGIBLE.value)
    payload.setdefault("freshness", FreshnessState.FRESH.value)
    payload.setdefault("applicability_limitations", ("Abstract and citation context require human review; this record does not prove diagnosis.",))
    payload.setdefault("concise_paraphrase", "Citation retrieved for bounded candidate review; interpretation remains a human decision.")
    payload.setdefault("doi", None)
    payload.setdefault("evidence_location", None)
    payload.setdefault("human_review_state", "pending")
    payload.setdefault("human_review_required", True)
    payload.setdefault("source_classification", "retrieved")
    without_identity = dict(payload)
    without_identity.pop("normalized_identity_sha256", None)
    payload["normalized_identity_sha256"] = _normalized_identity(without_identity)
    return PaperEvidenceRecord.model_validate(payload)


def parse_pubmed_records(
    body: bytes | str,
    *,
    raw_digest: str,
    timestamp: str,
    source_release: str,
    candidate_binding: CandidateBinding | None = None,
) -> tuple[tuple[PaperEvidenceRecord, ...], tuple[DatabaseEvidenceRecord, ...]]:
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    payload: Any
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    items: list[dict[str, Any]] = []
    if isinstance(payload, dict) and isinstance(payload.get("papers"), list):
        items = [item for item in payload["papers"] if isinstance(item, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        result = payload["result"]
        for uid in result.get("uids", []):
            item = result.get(str(uid))
            if isinstance(item, dict):
                items.append({
                    "pmid": item.get("uid", uid),
                    "title": item.get("title", "Untitled PubMed record"),
                    "authors_summary": tuple((author.get("name") or author.get("authtype") or "author") for author in item.get("authors", []) if isinstance(author, dict)),
                    "journal": item.get("fulljournalname") or item.get("source") or "PubMed",
                    "publication_year": int(str(item.get("pubdate", "2000"))[:4]) if str(item.get("pubdate", "2000"))[:4].isdigit() else 2000,
                    "publication_type": tuple(item.get("pubtype", []) or ()),
                    "abstract_available": False,
                    "doi": next((str(article_id.get("value")) for article_id in item.get("articleids", []) if isinstance(article_id, dict) and article_id.get("idtype") == "doi"), None),
                })
    elif "<" in text and "PubmedArticle" in text:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(text)
        for article in root.findall(".//PubmedArticle"):
            pmid = article.findtext(".//PMID")
            title = " ".join("".join(article.find(".//ArticleTitle").itertext()).split()) if article.find(".//ArticleTitle") is not None else "Untitled PubMed record"
            journal = article.findtext(".//Journal/Title") or "PubMed"
            year = article.findtext(".//PubDate/Year") or "2000"
            items.append({"pmid": pmid, "title": title, "journal": journal, "publication_year": int(year) if year.isdigit() else 2000, "abstract_available": article.find(".//Abstract") is not None})
    papers = tuple(_paper_payload(item, raw_digest=raw_digest, timestamp=timestamp, source_release=source_release, candidate_binding=candidate_binding) for item in items if item.get("pmid") and str(item.get("pmid")).isdigit())
    return papers, ()


def _database_payload(item: dict[str, Any], *, source_id: str, raw_digest: str, timestamp: str, source_release: str, candidate_binding: CandidateBinding | None) -> DatabaseEvidenceRecord:
    payload = dict(item)
    record_id = str(payload.pop("record_id", payload.pop("variation_id", payload.pop("id", "record"))))
    payload.setdefault("evidence_id", f"{source_id}-record-{re.sub(r'[^A-Za-z0-9_.:-]+', '-', record_id)}")
    payload["source_id"] = source_id
    payload["record_id"] = record_id
    payload.setdefault("record_type", "typed_database_record")
    payload.setdefault("source_release", source_release)
    payload.setdefault("collection_method", "official typed adapter")
    payload["raw_response_sha256"] = raw_digest
    payload["candidate_binding"] = candidate_binding.model_dump(mode="json") if candidate_binding else payload.get("candidate_binding")
    payload.setdefault("assembly", None)
    payload.setdefault("classification", None)
    payload.setdefault("record_fields", {})
    payload.setdefault("evidence_role", EvidenceRole.UNRESOLVED.value)
    payload.setdefault("evidence_lifecycle_state", EvidenceLifecycleState.ELIGIBLE.value)
    payload.setdefault("freshness", FreshnessState.FRESH.value)
    payload.setdefault("human_review_state", "pending")
    payload.setdefault("human_review_required", True)
    payload.setdefault("source_classification", "retrieved")
    payload.setdefault("citations", ())
    payload.setdefault("conflict_ids", ())
    payload.setdefault("limitations", ("External database context is not InSilicoPop final classification.",))
    payload_without_identity = dict(payload)
    payload_without_identity.pop("normalized_identity_sha256", None)
    payload["normalized_identity_sha256"] = _normalized_identity(payload_without_identity)
    return DatabaseEvidenceRecord.model_validate(payload)


def parse_clinvar_records(
    body: bytes | str,
    *,
    raw_digest: str,
    timestamp: str,
    source_release: str,
    candidate_binding: CandidateBinding | None = None,
) -> tuple[DatabaseEvidenceRecord, ...]:
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    payload: Any = json.loads(text)
    items: list[dict[str, Any]] = []
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        items = [item for item in payload["records"] if isinstance(item, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        result = payload["result"]
        for uid in result.get("uids", []):
            item = result.get(str(uid))
            if isinstance(item, dict):
                record_id = str(item.get("accession") or item.get("variationid") or item.get("uid") or uid)
                items.append({
                    "record_id": record_id,
                    "record_type": item.get("obj_type", "ClinVar record"),
                    "classification": item.get("clinical_significance") or item.get("clinical_significance_description"),
                    "record_fields": {
                        "variation_id": item.get("variationid"),
                        "accession": item.get("accession"),
                        "condition": item.get("condition"),
                        "submitter": item.get("submitter"),
                        "review_status": item.get("review_status"),
                        "assertion_criteria": item.get("assertion_criteria"),
                        "evaluation_date": item.get("date_last_evaluated"),
                        "updated": item.get("updatedate"),
                    },
                })
    records = [_database_payload(item, source_id="clinvar", raw_digest=raw_digest, timestamp=timestamp, source_release=source_release, candidate_binding=candidate_binding) for item in items]
    if len(records) > 1:
        ids = tuple(item.evidence_id for item in records)
        updated_records: list[DatabaseEvidenceRecord] = []
        for item in records:
            payload = item.model_dump(mode="json")
            payload["conflict_ids"] = ids
            payload["evidence_role"] = EvidenceRole.UNRESOLVED.value
            payload.pop("normalized_identity_sha256", None)
            payload["normalized_identity_sha256"] = _normalized_identity(payload)
            updated_records.append(DatabaseEvidenceRecord.model_validate(payload))
        records = updated_records
    return tuple(records)


def parse_ensembl_records(
    body: bytes | str,
    *,
    raw_digest: str,
    timestamp: str,
    source_release: str,
    candidate_binding: CandidateBinding | None = None,
) -> tuple[DatabaseEvidenceRecord, ...]:
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    payload: Any = json.loads(text)
    if isinstance(payload, dict) and isinstance(payload.get("vep"), list):
        items = payload["vep"]
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    records: list[DatabaseEvidenceRecord] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        transcript_consequences = item.get("transcript_consequences") or []
        records.append(_database_payload({
            "record_id": str(item.get("id") or item.get("input") or f"vep-{index}"),
            "record_type": "Ensembl VEP consequence",
            "assembly": item.get("assembly_name"),
            "record_fields": {
                "ensembl_release": item.get("seq_region_name") or source_release,
                "id": item.get("id"),
                "input": item.get("input"),
                "allele_string": item.get("allele_string"),
                "most_severe_consequence": item.get("most_severe_consequence"),
                "transcript_consequences": transcript_consequences,
                "gene_symbols": sorted({str(tc.get("gene_symbol")) for tc in transcript_consequences if isinstance(tc, dict) and tc.get("gene_symbol")}),
                "transcript_ids": sorted({str(tc.get("transcript_id")) for tc in transcript_consequences if isinstance(tc, dict) and tc.get("transcript_id")}),
            },
        }, source_id="ensembl", raw_digest=raw_digest, timestamp=timestamp, source_release=source_release, candidate_binding=candidate_binding))
    return tuple(records)


__all__ = [
    "RETRIEVAL_REGISTRY_VERSION",
    "RetrievalRegistryDefinition",
    "RETRIEVAL_REGISTRY",
    "registered_retrieval_adapters",
    "get_retrieval_definition",
    "validate_allowlisted_url",
    "validate_redirect",
    "validate_response",
    "TransportResponse",
    "FixtureTransport",
    "UrllibTransport",
    "RetrievalUnavailable",
    "RetrievalCache",
    "RetrievalResult",
    "ControlledRetrievalService",
    "parse_esearch_ids",
    "parse_pubmed_records",
    "parse_clinvar_records",
    "parse_ensembl_records",
]
