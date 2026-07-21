<script lang="ts">
  import { flip } from "svelte/animate";
  import { onDestroy, onMount, tick } from "svelte";
  import { fade, slide } from "svelte/transition";
  import JSZip from "jszip";
  import html2canvas from "html2canvas";
  import { get_api, post_api } from "$lib/api";
  import { VERSION } from "$lib/version";
  import WorkspaceToolbar from "$lib/components/workspace/workspace-toolbar.svelte";
  import type {
    MediaFilterCatalogResponse,
    MediaFilterOptionResponse,
    MieOperationsResponse,
    OperationActionManifestAction,
    OperationAuditListResponse,
    OperationExecutionHistoryListResponse,
    OperationExecutionSessionResponse,
    OperationWorkflowResponse,
    OperationsFileEvidence,
    OperationsWorkflowAsset,
    WorkflowStageKey,
  } from "$lib/types/shared";
  import { formatFileSize } from "$lib/utils/formatters";
  import {
    applyExecutionSessionToWorkspace,
    confidenceBarClass,
    confidenceLabel,
    filterAndSortAssets,
    formatDuration,
    riskLabel,
    stageStats,
    stageTitle,
    summarizeBulkAction,
    summarizeExecutionSession,
    toggleAssetSelection,
  } from "$lib/operations/workspace-view.js";

  type LocalMediaFilter = "all" | "movies" | "series" | "anime" | "collections";
  type LocalReadinessFilter =
    | "all"
    | "ready"
    | "blocked"
    | "needs_review"
    | "high_confidence"
    | "low_confidence";
  type SortBy = "recovery" | "title" | "confidence";
  type ViewMode = "grid" | "list";
  type CockpitTab =
    | "overview"
    | "status"
    | "files"
    | "applications"
    | "relationships"
    | "timeline"
    | "actions"
    | "execution"
    | "history"
    | "logs";
  type OperationsWorkspacePrefs = {
    search: string;
    sortBy: SortBy;
    sortOrder: "asc" | "desc";
    candidatesOnly: boolean;
    arrFilterIds: number[];
    decisionFilterIds: number[];
    smartFilterIds: number[];
    selectedStage: WorkflowStageKey;
    selectedFilter: string | null;
    selectedMediaType: LocalMediaFilter;
    selectedReadiness: LocalReadinessFilter;
    showCompleted: boolean;
    pageSize: number;
    currentPage: number;
    visibleAssetLimit?: number;
    posterSize: number;
    displayMode: ViewMode;
  };

  const PREFS_KEY = "operations_workspace_prefs_v082";
  const POLL_INTERVAL_MS = 900;
  const sortByOptions = [
    { value: "recovery", label: "Recovery" },
    { value: "confidence", label: "Confidence" },
    { value: "title", label: "Title" },
  ];
  const toolbarActions = [
    { key: "preview", label: "Preview" },
    { key: "validate", label: "Validate" },
    { key: "execute", label: "Execute" },
    { key: "clear", label: "Clear Selection" },
  ];
  const cockpitTabs: Array<{ key: CockpitTab; label: string }> = [
    { key: "overview", label: "Overview" },
    { key: "status", label: "Status" },
    { key: "files", label: "Files" },
    { key: "relationships", label: "Relationships" },
    { key: "applications", label: "Applications" },
    { key: "timeline", label: "Timeline" },
    { key: "actions", label: "Actions" },
    { key: "execution", label: "Execution" },
    { key: "history", label: "History" },
    { key: "logs", label: "Logs" },
  ];

  let loading = $state(true);
  let error = $state("");
  let workspace = $state<MieOperationsResponse | null>(null);
  let auditTrail = $state<OperationAuditListResponse | null>(null);
  let executionHistory = $state<OperationExecutionHistoryListResponse | null>(
    null,
  );
  let filterCatalog = $state<MediaFilterCatalogResponse | null>(null);

  let search = $state("");
  let sortBy = $state<SortBy>("recovery");
  let sortOrder = $state<"asc" | "desc">("desc");
  let candidatesOnly = $state(false);
  let arrFilterIds = $state<number[]>([]);
  let decisionFilterIds = $state<number[]>([]);
  let smartFilterIds = $state<number[]>([]);
  let pageSize = $state(50);
  let currentPage = $state(1);
  let posterSize = $state(170);
  let displayMode = $state<ViewMode>("grid");

  let frontendRenderingMs = $state(0);
  let imageLoadingMs = $state(0);
  let networkLog = $state<
    Array<{
      method: string;
      url: string;
      status: number;
      duration_ms: number;
      started_at: string;
    }>
  >([]);
  let consoleLog = $state<
    Array<{ level: string; message: string; at: string }>
  >([]);
  let exporting = $state<"snapshot" | "bundle" | null>(null);

  const performanceProfile = $derived.by(() => {
    return (
      workspace?.performance ?? {
        backend_api_ms: 0,
        filesystem_analysis_ms: 0,
        artwork_loading_ms: 0,
        identity_graph_ms: 0,
        torrent_intelligence_ms: 0,
        narrative_generation_ms: 0,
        stages: [],
      }
    );
  });

  let selectedStage = $state<WorkflowStageKey>("download");
  let selectedFilter = $state<string | null>(null);
  let selectedMediaType = $state<LocalMediaFilter>("all");
  let selectedReadiness = $state<LocalReadinessFilter>("all");
  let showCompleted = $state(false);

  let stageSelections = $state<Record<string, Set<string>>>({});
  let lastClickedByStage = $state<Record<string, string | null>>({});
  let selectedAssetId = $state<string | null>(null);
  let cockpitTab = $state<CockpitTab>("overview");
  let loadedCockpitKeys = $state<Set<string>>(new Set());
  let inspectorPreview = $state<OperationWorkflowResponse | null>(null);
  let inspectorValidation = $state<OperationWorkflowResponse | null>(null);
  let inspectorTabBusy = $state(false);
  let inspectorActionBusy = $state(false);
  let inspectorActionMessage = $state("");

  let workflowBusy = $state(false);
  let workflowMode = $state<"preview" | "validate" | null>(null);
  let workflowProgress = $state({ total: 0, completed: 0, failed: 0 });
  let workflowError = $state("");
  let workflowResults = $state<OperationWorkflowResponse[]>([]);

  let executionSession = $state<OperationExecutionSessionResponse | null>(null);
  let executionError = $state("");
  let executionPollHandle = $state<ReturnType<typeof setInterval> | null>(null);
  let executionPollInFlight = $state(false);
  let executionStarting = $state(false);
  let appliedExecutionIds = $state<Set<string>>(new Set());

  const selectedFilterOptions = $derived.by(() => {
    const options: MediaFilterOptionResponse[] = [];
    for (const option of filterCatalog?.imported ?? []) {
      if (option.filter_id && arrFilterIds.includes(option.filter_id)) {
        options.push(option);
      }
    }
    for (const option of filterCatalog?.native ?? []) {
      if (option.filter_id && decisionFilterIds.includes(option.filter_id)) {
        options.push(option);
      }
    }
    for (const option of filterCatalog?.smart ?? []) {
      if (option.filter_id && smartFilterIds.includes(option.filter_id)) {
        options.push(option);
      }
    }
    return options;
  });

  const stageRows = $derived.by(() => {
    return (workspace?.workflow?.stages ?? []).filter(
      (row) => showCompleted || row.key !== "completed",
    );
  });

  const allWorkflowAssets = $derived.by(() => {
    return (workspace?.workflow?.stages ?? []).flatMap(
      (stage) => stage.assets ?? [],
    );
  });

  const activeStage = $derived.by(() => {
    return (
      stageRows.find((row) => row.key === selectedStage) ?? stageRows[0] ?? null
    );
  });

  const activeStageAssets = $derived.by(() => activeStage?.assets ?? []);

  const filteredAssets = $derived.by(() => {
    return filterAndSortAssets(activeStageAssets, {
      search,
      filterKey: selectedFilter,
      mediaType: selectedMediaType,
      readiness: selectedReadiness,
      sortBy,
      sortOrder,
    }) as OperationsWorkflowAsset[];
  });

  const totalPages = $derived.by(() => {
    return Math.max(
      1,
      Math.ceil(filteredAssets.length / Math.max(1, pageSize)),
    );
  });

  const currentPageClamped = $derived.by(() => {
    return Math.min(Math.max(1, currentPage), totalPages);
  });

  const pageStartIndex = $derived.by(() => {
    return (currentPageClamped - 1) * Math.max(1, pageSize);
  });

  const pageEndIndexExclusive = $derived.by(() => {
    return Math.min(
      filteredAssets.length,
      pageStartIndex + Math.max(1, pageSize),
    );
  });

  const displayedAssets = $derived.by(() => {
    return filteredAssets.slice(pageStartIndex, pageEndIndexExclusive);
  });

  const orderedFilteredIds = $derived.by(() =>
    filteredAssets.map((asset) => asset.id),
  );
  const displayedIds = $derived.by(() =>
    displayedAssets.map((asset) => asset.id),
  );

  const pageNumbers = $derived.by(() => {
    const windowSize = 7;
    const page = currentPageClamped;
    const total = totalPages;
    if (total <= windowSize) {
      return Array.from({ length: total }, (_, index) => index + 1);
    }
    const start = Math.max(1, page - 3);
    const end = Math.min(total, start + windowSize - 1);
    const adjustedStart = Math.max(1, end - windowSize + 1);
    return Array.from(
      { length: end - adjustedStart + 1 },
      (_, index) => adjustedStart + index,
    );
  });

  const selectedIdsInStage = $derived.by(() => {
    const key = activeStage?.key ?? "download";
    return stageSelections[key] ?? new Set<string>();
  });

  const selectedAssets = $derived.by(() => {
    return filteredAssets.filter((asset) => selectedIdsInStage.has(asset.id));
  });

  const allSelectedIds = $derived.by(() => {
    const ids = new Set<string>();
    for (const values of Object.values(stageSelections)) {
      for (const id of values) ids.add(id);
    }
    return ids;
  });

  const allSelectedAssets = $derived.by(() => {
    return allWorkflowAssets.filter((asset) => allSelectedIds.has(asset.id));
  });

  const totalSelectedCount = $derived.by(() => {
    return Object.values(stageSelections).reduce(
      (count, ids) => count + ids.size,
      0,
    );
  });

  const displayedSelectedCount = $derived.by(() => {
    return displayedAssets.filter((asset) => selectedIdsInStage.has(asset.id))
      .length;
  });

  const allDisplayedSelected = $derived.by(() => {
    return (
      displayedAssets.length > 0 &&
      displayedSelectedCount === displayedAssets.length
    );
  });

  const someDisplayedSelected = $derived.by(() => {
    return (
      displayedSelectedCount > 0 &&
      displayedSelectedCount < displayedAssets.length
    );
  });

  const selectableRecommendationIds = $derived.by(() => {
    return new Set(
      (workspace?.recommendations.items ?? []).map((row) => row.id),
    );
  });

  const selectedRecommendationIds = $derived.by(() => {
    return Array.from(
      new Set(
        allSelectedAssets
          .map((asset) => asset.id)
          .filter((id) => selectableRecommendationIds.has(id)),
      ),
    );
  });

  const selectedAsset = $derived.by(() => {
    if (!selectedAssetId) return null;
    return (
      allWorkflowAssets.find((asset) => asset.id === selectedAssetId) ?? null
    );
  });

  const stageFilterRows = $derived.by(() => {
    const counts = new Map<string, number>();
    const labels = new Map(
      (workspace?.workflow?.filters ?? []).map((row) => [row.key, row.title]),
    );
    for (const asset of activeStageAssets) {
      for (const key of asset.filters ?? []) {
        counts.set(key, (counts.get(key) ?? 0) + 1);
      }
    }
    return Array.from(counts.entries())
      .map(([key, count]) => ({
        key,
        title: labels.get(key) ?? key.replaceAll("_", " "),
        count,
      }))
      .sort((a, b) => b.count - a.count || a.title.localeCompare(b.title));
  });

  const bulkSummary = $derived.by(() => summarizeBulkAction(workflowResults));
  const workflowProgressPercent = $derived.by(() => {
    if (!workflowProgress.total) return 0;
    return Math.round(
      (workflowProgress.completed / workflowProgress.total) * 100,
    );
  });

  const executionActive = $derived.by(() => {
    return (
      !!executionSession &&
      ["queued", "running"].includes(executionSession.status)
    );
  });

  const executionProgressPercent = $derived.by(() => {
    if (!executionSession?.total) return 0;
    return Math.round(
      (executionSession.completed / executionSession.total) * 100,
    );
  });

  const executionSummary = $derived.by(() => {
    return executionSession
      ? summarizeExecutionSession(executionSession)
      : null;
  });

  const executionItemsByRecommendation = $derived.by(() => {
    return new Map(
      (executionSession?.items ?? []).map((item) => [
        item.recommendation_id,
        item,
      ]),
    );
  });

  const selectedExecutionItem = $derived.by(() => {
    if (!selectedAssetId) return null;
    return executionItemsByRecommendation.get(selectedAssetId) ?? null;
  });

  const selectedRecommendation = $derived.by(() => {
    if (!selectedAssetId) return null;
    return (
      workspace?.recommendations.items.find(
        (item) => item.id === selectedAssetId,
      ) ?? null
    );
  });

  const selectedManifestActions = $derived.by(() => {
    return (selectedAsset?.action_manifest?.available_actions ??
      selectedRecommendation?.action_manifest?.available_actions ??
      []) as OperationActionManifestAction[];
  });

  const selectedPrimaryAction = $derived.by(() => {
    if (!selectedAsset) return null;
    const primaryId = normalizeActionId(
      selectedAsset.next_action ?? selectedRecommendation?.action ?? "",
    );
    return (
      selectedManifestActions.find((row) => row.id === primaryId) ??
      selectedManifestActions.find((row) => row.presentation === "required") ??
      selectedManifestActions.find(
        (row) => row.presentation === "recommended",
      ) ??
      null
    );
  });

  const selectedRequiredActions = $derived.by(() => {
    return selectedManifestActions.filter(
      (row) => row.presentation === "required",
    );
  });

  const selectedRecommendedActions = $derived.by(() => {
    return selectedManifestActions.filter(
      (row) => row.presentation === "recommended",
    );
  });

  const groupedSecondaryActions = $derived.by(() => {
    const groups = new Map<string, OperationActionManifestAction[]>();
    for (const row of selectedManifestActions.filter(
      (action) => action.presentation === "secondary",
    )) {
      const key = row.category || "maintenance";
      const current = groups.get(key) ?? [];
      current.push(row);
      groups.set(key, current);
    }
    return Array.from(groups.entries()).map(([category, actions]) => ({
      category,
      actions,
    }));
  });

  const selectedTimeline = $derived.by(() => {
    if (!selectedAsset) return [];
    const mediaType = selectedAsset.media_type ?? null;
    const targetId = selectedAsset.target_id
      ? Number(selectedAsset.target_id)
      : null;
    return (workspace?.timeline_summary?.highlights ?? []).filter((event) => {
      if (event.media_type && mediaType && event.media_type !== mediaType)
        return false;
      if (
        event.media_id !== null &&
        targetId !== null &&
        event.media_id !== targetId
      )
        return false;
      return (
        event.title.toLowerCase().includes(selectedAsset.title.toLowerCase()) ||
        event.media_id === targetId
      );
    });
  });

  const selectedHistoryRows = $derived.by(() => {
    if (!selectedAsset) return [];
    const targetId = selectedAsset.target_id;
    return (executionHistory?.items ?? []).filter((row) =>
      row.items.some(
        (item) =>
          item.recommendation_id === selectedAsset.id ||
          item.target_id === targetId,
      ),
    );
  });

  const selectedAuditRows = $derived.by(() => {
    if (!selectedAsset) return [];
    return (auditTrail?.items ?? []).filter((row) => {
      if (selectedAsset.target_id && row.target_id === selectedAsset.target_id)
        return true;
      return row.target_type === selectedAsset.target_type;
    });
  });

  const selectedLocations = $derived.by(() => {
    return selectedAsset?.file_evidence ?? [];
  });

  const selectedApplications = $derived.by(() => {
    return selectedAsset?.application_evidence ?? [];
  });

  const selectedRelationships = $derived.by(() => {
    return selectedAsset?.relationship_evidence ?? [];
  });

  const fileComparisonSummary = $derived.by(() => {
    if (!selectedAsset || selectedLocations.length === 0) {
      return "No filesystem evidence is currently available for comparison.";
    }
    if (selectedAsset.filesystem_comparison_summary) {
      return selectedAsset.filesystem_comparison_summary;
    }
    return "Filesystem comparison is unavailable because semantic hierarchy evidence has not been generated for this asset.";
  });

  function formatEvidenceDate(value: string | null | undefined) {
    if (!value) return "Unavailable";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
  }

  function filePathDisplay(row: OperationsFileEvidence) {
    return row.absolute_path ?? row.path ?? "Unavailable";
  }

  function fileOperationalStatus(row: OperationsFileEvidence) {
    if (row.state === "duplicate") return "Needs Action";
    if (row.state === "missing") return "Needs Action";
    if (row.state === "unavailable") return "Needs Attention";
    if (row.import_eligibility === "eligible" && row.state === "available")
      return "Correct";
    if (row.import_eligibility === "review required") return "Needs Review";
    if (row.state === "partial") return "Needs Review";
    return "Review";
  }

  function fileRecommendedAction(row: OperationsFileEvidence) {
    if (row.state === "duplicate") {
      return "Another primary media copy exists outside the canonical managed folder. Review and remove or reconcile the extra copy.";
    }
    if (row.state === "missing") {
      return "The expected filesystem object is missing. Verify path mapping or restore the file.";
    }
    if (row.state === "unavailable") {
      return "Provider path evidence is unavailable. Link or refresh the owning application metadata.";
    }
    if (row.import_eligibility === "eligible" && row.state === "available") {
      return "No action required. This location is currently correct.";
    }
    if (row.import_eligibility === "review required") {
      return "File is present but placement needs review against the managed destination.";
    }
    return "Review this path with the linked evidence and take the recommended lifecycle action.";
  }

  function fileEvidenceAdvancedFields(row: OperationsFileEvidence) {
    return [
      { label: "Hierarchy Role", value: row.hierarchy_role ?? "unknown" },
      {
        label: "Absolute Path",
        value: row.absolute_path ?? row.path ?? "Unavailable",
      },
      { label: "Filename", value: row.filename ?? "Unavailable" },
      { label: "Dataset", value: row.dataset ?? "Unavailable" },
      { label: "Pool", value: row.pool ?? "Unavailable" },
      { label: "Filesystem", value: row.filesystem ?? "Unavailable" },
      {
        label: "Exists",
        value: row.exists === null ? "Unavailable" : row.exists ? "Yes" : "No",
      },
      { label: "Owner", value: row.owner ?? "Unavailable" },
      { label: "Group", value: row.group ?? "Unavailable" },
      { label: "Permissions", value: row.permissions ?? "Unavailable" },
      {
        label: "File Size",
        value:
          row.file_size === null || row.file_size === undefined
            ? "Unavailable"
            : formatFileSize(row.file_size),
      },
      { label: "Created", value: formatEvidenceDate(row.created) },
      { label: "Modified", value: formatEvidenceDate(row.modified) },
      {
        label: "Expected Destination",
        value: row.expected_destination ?? "Unavailable",
      },
      { label: "Known Copy Of", value: row.known_copy_of ?? "Unavailable" },
      {
        label: "Import Eligibility",
        value: row.import_eligibility ?? "Unavailable",
      },
    ];
  }

  function workflowOutcome(asset: OperationsWorkflowAsset | null | undefined) {
    return asset?.action_manifest?.workflow_outcome ?? "in_progress";
  }

  function workflowOutcomeLabel(
    asset: OperationsWorkflowAsset | null | undefined,
  ) {
    const outcome = workflowOutcome(asset);
    if (outcome === "blocked") return "Blocked";
    if (outcome === "completed") return "Complete";
    return "In Progress";
  }

  function workflowOutcomeClass(
    asset: OperationsWorkflowAsset | null | undefined,
  ) {
    const outcome = workflowOutcome(asset);
    if (outcome === "blocked") {
      return "border-destructive/60 bg-destructive/10 text-destructive";
    }
    if (outcome === "completed") {
      return "border-emerald-500/60 bg-emerald-500/10 text-emerald-200";
    }
    return "border-primary/50 bg-primary/10 text-primary";
  }

  function assetPrimaryAction(asset: OperationsWorkflowAsset) {
    const primaryId = normalizeActionId(asset.next_action ?? "");
    return (
      asset.action_manifest.available_actions.find(
        (row) => row.id === primaryId,
      ) ??
      asset.action_manifest.available_actions.find(
        (row) => row.presentation === "required",
      ) ??
      asset.action_manifest.available_actions.find(
        (row) => row.presentation === "recommended",
      ) ??
      null
    );
  }

  function assetActionHeading(asset: OperationsWorkflowAsset) {
    const primary = assetPrimaryAction(asset);
    if (primary?.presentation === "required") return "Required Action";
    if (primary?.presentation === "recommended") return "Recommended Action";
    return "Next Step";
  }

  function assetActionLabel(asset: OperationsWorkflowAsset) {
    return (
      assetPrimaryAction(asset)?.label ?? asset.next_action.replaceAll("_", " ")
    );
  }

  function workflowSummary(asset: OperationsWorkflowAsset | null | undefined) {
    if (!asset) return "Workflow state unavailable.";
    return (
      asset.action_manifest.workflow_summary ??
      asset.case_summary ??
      asset.reason ??
      "Workflow state unavailable."
    );
  }

  function actionPresentationLabel(action: OperationActionManifestAction) {
    if (action.presentation === "required") return "Required Action";
    if (action.presentation === "recommended") return "Recommended Action";
    return "Additional Action";
  }

  function actionPresentationClass(action: OperationActionManifestAction) {
    if (action.presentation === "required") {
      return "border-destructive/60 bg-destructive/10 text-destructive";
    }
    if (action.presentation === "recommended") {
      return "border-emerald-500/60 bg-emerald-500/10 text-emerald-200";
    }
    return "border-border text-muted-foreground";
  }

  function narrativeOutcomeLabel(
    asset: OperationsWorkflowAsset | null | undefined,
  ) {
    const outcome = asset?.narrative?.outcome;
    if (outcome === "attention_required") return "Attention Required";
    if (outcome === "healthy_with_recommendations")
      return "Healthy With Recommendations";
    return "Healthy";
  }

  function narrativeOutcomeClass(
    asset: OperationsWorkflowAsset | null | undefined,
  ) {
    const outcome = asset?.narrative?.outcome;
    if (outcome === "attention_required") {
      return "border-destructive/60 bg-destructive/10 text-destructive";
    }
    if (outcome === "healthy_with_recommendations") {
      return "border-amber-400/60 bg-amber-500/10 text-amber-200";
    }
    return "border-emerald-500/60 bg-emerald-500/10 text-emerald-200";
  }

  function narrativeWhat(asset: OperationsWorkflowAsset | null | undefined) {
    return asset?.narrative?.what ?? workflowSummary(asset);
  }

  function narrativeWhere(asset: OperationsWorkflowAsset | null | undefined) {
    return asset?.narrative?.where ?? null;
  }

  function narrativeLines(
    asset: OperationsWorkflowAsset | null | undefined,
    key: "why" | "impact" | "next",
  ) {
    return asset?.narrative?.[key] ?? [];
  }

  function narrativeSummary(
    asset: OperationsWorkflowAsset | null | undefined,
  ): string {
    if (!asset) return "Workflow state unavailable.";
    if (asset.current_stage === "download") return "Download in progress.";
    if (asset.current_stage === "import") return "Waiting for import.";
    if (asset.current_stage === "retention")
      return "Seeding and retention active.";
    if (asset.current_stage === "cleanup") return "Ready for cleanup.";
    if (asset.current_stage === "completed") return "No action required.";
    return workflowSummary(asset);
  }

  function confidenceSummary(confidence: number | null | undefined): string {
    const bucket = confidenceLabel(confidence);
    if (bucket === "High") {
      return "MediaMasterr is confident this recommendation is correct.";
    }
    if (bucket === "Medium") {
      return "Some evidence is incomplete. Validate before executing.";
    }
    return "Manual review recommended before taking action.";
  }

  function torrentOperationalState(state: string | null | undefined): {
    label: string;
    what: string;
    action: string;
  } {
    const raw = String(state || "")
      .trim()
      .toLowerCase();
    if (!raw) {
      return {
        label: "No Activity",
        what: "No download or upload activity detected.",
        action: "No immediate action required.",
      };
    }
    if (raw.includes("down") || raw.includes("dl")) {
      return {
        label: "Downloading",
        what: "Receiving data.",
        action: "No action unless progress remains stalled.",
      };
    }
    if (raw.includes("seed") || raw.includes("upload") || raw.includes("up")) {
      return {
        label: "Seeding",
        what: "Upload requirements are still active.",
        action: "Keep seeding until retention and ratio goals are complete.",
      };
    }
    if (raw.includes("complete") || raw.includes("finished")) {
      return {
        label: "Waiting for Import",
        what: "Download complete. Waiting for Sonarr or Radarr import.",
        action: "No action required unless import remains pending.",
      };
    }
    if (raw.includes("stall")) {
      return {
        label: "No Activity",
        what: "No download or upload activity detected.",
        action: "Run recheck or resume if this persists.",
      };
    }
    if (raw.includes("peer")) {
      return {
        label: "Waiting for Peers",
        what: "Connected but no peers are currently available.",
        action: "No immediate action required; monitor peer availability.",
      };
    }
    if (raw.includes("queue") || raw.includes("queued")) {
      return {
        label: "Queued",
        what: "Queued and waiting for an active transfer slot.",
        action: "No action unless queue never progresses.",
      };
    }
    if (raw.includes("pause")) {
      return {
        label: "Paused",
        what: "Transfer is paused.",
        action: "Resume when transfer should continue.",
      };
    }
    return {
      label: "No Activity",
      what: `State reported as ${state}.`,
      action: "Review transfer state in qBittorrent.",
    };
  }

  function setPage(page: number) {
    currentPage = Math.min(Math.max(1, page), totalPages);
  }

  function networkSummary() {
    const byStatus = new Map<number, number>();
    let totalDuration = 0;
    for (const row of networkLog) {
      byStatus.set(row.status, (byStatus.get(row.status) ?? 0) + 1);
      totalDuration += row.duration_ms;
    }
    const status_counts: Record<string, number> = {};
    for (const [status, count] of byStatus.entries()) {
      status_counts[String(status)] = count;
    }
    return {
      total_requests: networkLog.length,
      average_duration_ms:
        networkLog.length > 0
          ? Math.round(totalDuration / networkLog.length)
          : 0,
      status_counts,
      requests: networkLog,
    };
  }

  async function captureSnapshotPng(): Promise<Blob> {
    const node = document.querySelector("main") ?? document.body;
    const canvas = await html2canvas(node as HTMLElement, {
      backgroundColor: "#0b0d10",
      useCORS: true,
      logging: false,
    });
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (!blob) {
          reject(new Error("Failed to capture snapshot image."));
          return;
        }
        resolve(blob);
      }, "image/png");
    });
  }

  function downloadBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function exportSnapshot() {
    if (!workspace) return;
    exporting = "snapshot";
    inspectorActionMessage = "Capturing snapshot...";
    try {
      const snapshotImage = await captureSnapshotPng();
      const snapshotState = {
        schema_version: "mmr.snapshot.v1",
        generated_at: new Date().toISOString(),
        route: window.location.hash || window.location.pathname,
        selected_asset: selectedAsset?.id ?? null,
        inspector_tab: cockpitTab,
        cockpit_state: {
          selected_filter: selectedFilter,
          selected_stage: selectedStage,
          selected_media_type: selectedMediaType,
          selected_readiness: selectedReadiness,
        },
        filters: {
          search,
          candidates_only: candidatesOnly,
          arr_filter_ids: arrFilterIds,
          decision_filter_ids: decisionFilterIds,
          smart_filter_ids: smartFilterIds,
        },
        selected_arr_application:
          selectedAsset?.media_type === "series"
            ? "Sonarr"
            : selectedAsset?.media_type === "movie"
              ? "Radarr"
              : null,
        pagination: {
          page: currentPageClamped,
          page_size: pageSize,
          total_pages: totalPages,
          total_assets: filteredAssets.length,
          display_start: filteredAssets.length === 0 ? 0 : pageStartIndex + 1,
          display_end: pageEndIndexExclusive,
        },
      };
      const zip = new JSZip();
      zip.file("snapshot.png", snapshotImage);
      zip.file("snapshot.json", JSON.stringify(snapshotState, null, 2));
      const blob = await zip.generateAsync({ type: "blob" });
      downloadBlob(
        blob,
        `mediamasterr-snapshot-${new Date().toISOString().replaceAll(":", "-")}.zip`,
      );
      inspectorActionMessage = "Snapshot exported.";
    } catch (e: any) {
      inspectorActionMessage = e?.message ?? "Snapshot export failed.";
    } finally {
      exporting = null;
    }
  }

  async function exportSupportBundle() {
    if (!workspace) return;
    exporting = "bundle";
    inspectorActionMessage = "Building support bundle...";
    try {
      const snapshotImage = await captureSnapshotPng();
      const zip = new JSZip();
      const generatedAt = new Date().toISOString();

      zip.file("snapshot.png", snapshotImage);
      zip.file(
        "selected_asset.json",
        JSON.stringify(selectedAsset ?? null, null, 2),
      );
      zip.file("workflow.json", JSON.stringify(workspace.workflow, null, 2));
      zip.file(
        "narrative.json",
        JSON.stringify(selectedAsset?.narrative ?? null, null, 2),
      );
      zip.file(
        "actions.json",
        JSON.stringify(selectedAsset?.action_manifest ?? null, null, 2),
      );
      zip.file(
        "evidence.json",
        JSON.stringify(
          {
            file_evidence: selectedAsset?.file_evidence ?? [],
            application_evidence: selectedAsset?.application_evidence ?? [],
            relationship_evidence: selectedAsset?.relationship_evidence ?? [],
          },
          null,
          2,
        ),
      );
      zip.file(
        "filesystem.json",
        JSON.stringify(
          {
            config: workspace.filesystem,
            comparison: selectedAsset?.filesystem_comparison_summary ?? null,
          },
          null,
          2,
        ),
      );
      zip.file(
        "relationships.json",
        JSON.stringify(selectedAsset?.relationship_evidence ?? [], null, 2),
      );
      zip.file(
        "timeline.json",
        JSON.stringify(
          {
            selected_asset_timeline: selectedTimeline,
            workflow_timeline: workspace.timeline_summary,
          },
          null,
          2,
        ),
      );
      zip.file(
        "browser-console.log",
        consoleLog
          .map((row) => `[${row.at}] [${row.level}] ${row.message}`)
          .join("\n"),
      );
      zip.file(
        "network-summary.json",
        JSON.stringify(networkSummary(), null, 2),
      );
      zip.file(
        "performance.json",
        JSON.stringify(
          {
            backend: workspace.performance,
            frontend: {
              rendering_ms: frontendRenderingMs,
              image_loading_ms: imageLoadingMs,
            },
          },
          null,
          2,
        ),
      );
      zip.file(
        "bundle-manifest.json",
        JSON.stringify(
          {
            schema_version: "mmr.support-bundle.v1",
            generated_at: generatedAt,
            files: [
              "snapshot.png",
              "selected_asset.json",
              "workflow.json",
              "narrative.json",
              "actions.json",
              "evidence.json",
              "filesystem.json",
              "relationships.json",
              "timeline.json",
              "browser-console.log",
              "network-summary.json",
              "performance.json",
              "application-versions.json",
              "environment.json",
            ],
          },
          null,
          2,
        ),
      );
      zip.file(
        "application-versions.json",
        JSON.stringify(
          {
            schema_version: "mmr.support-bundle.v1",
            generated_at: generatedAt,
            frontend_version: VERSION,
            backend_api: "/api/mie/operations",
          },
          null,
          2,
        ),
      );
      zip.file(
        "environment.json",
        JSON.stringify(
          {
            route: window.location.hash || window.location.pathname,
            user_agent: window.navigator.userAgent,
            selected_asset_id: selectedAsset?.id ?? null,
            selected_arr_application:
              selectedAsset?.media_type === "series"
                ? "Sonarr"
                : selectedAsset?.media_type === "movie"
                  ? "Radarr"
                  : null,
            pagination: {
              page: currentPageClamped,
              page_size: pageSize,
              total_pages: totalPages,
              total_assets: filteredAssets.length,
            },
            filters: {
              search,
              candidates_only: candidatesOnly,
              arr_filter_ids: arrFilterIds,
              decision_filter_ids: decisionFilterIds,
              smart_filter_ids: smartFilterIds,
            },
          },
          null,
          2,
        ),
      );

      const blob = await zip.generateAsync({ type: "blob" });
      downloadBlob(
        blob,
        `mediamasterr-support-bundle-${generatedAt.replaceAll(":", "-")}.zip`,
      );
      inspectorActionMessage = "Support bundle exported.";
    } catch (e: any) {
      inspectorActionMessage = e?.message ?? "Support bundle export failed.";
    } finally {
      exporting = null;
    }
  }

  function normalizeActionId(action: string) {
    const source = String(action || "")
      .trim()
      .toLowerCase();
    const aliases: Record<string, string> = {
      repair_import: "retry_import",
      review_identity: "repair_identity",
      cleanup_torrent: "delete_torrent",
      delete_files: "delete_torrent_and_files",
      monitor: "mark_resolved",
      monitor_detached_media: "mark_resolved",
      sync_request: "retry_download",
      detach_torrent: "delete_torrent",
    };
    return aliases[source] ?? source;
  }

  function cockpitLoadKey(tab: CockpitTab) {
    return `${selectedAssetId ?? "none"}:${tab}`;
  }

  async function ensureCockpitTabData(tab: CockpitTab) {
    if (!selectedRecommendation || !selectedAssetId) return;
    const key = cockpitLoadKey(tab);
    if (loadedCockpitKeys.has(key)) return;
    if (tab !== "execution" && tab !== "logs") {
      loadedCockpitKeys = new Set([...loadedCockpitKeys, key]);
      return;
    }

    inspectorTabBusy = true;
    try {
      if (tab === "execution") {
        inspectorPreview = await get_api<OperationWorkflowResponse>(
          `/api/operations/recommendations/${selectedAssetId}/preview`,
        );
        inspectorValidation = await get_api<OperationWorkflowResponse>(
          `/api/operations/recommendations/${selectedAssetId}/validate`,
        );
      }
      if (tab === "logs") {
        await loadHistory();
      }
      loadedCockpitKeys = new Set([...loadedCockpitKeys, key]);
    } catch (e: any) {
      inspectorActionMessage =
        e?.message ?? "Failed to load inspector tab data";
    } finally {
      inspectorTabBusy = false;
    }
  }

  async function selectCockpitTab(tab: CockpitTab) {
    cockpitTab = tab;
    await ensureCockpitTabData(tab);
  }

  async function copyPath(path: string | null | undefined) {
    if (!path) return;
    try {
      await navigator.clipboard.writeText(path);
      inspectorActionMessage = `Copied path: ${path}`;
    } catch {
      inspectorActionMessage = "Copy failed. Clipboard is unavailable.";
    }
  }

  function openFilesystemPath(path: string | null | undefined) {
    if (!path || typeof window === "undefined") return;
    const fileUrl = `file://${path.replaceAll("\\", "/")}`;
    window.open(fileUrl, "_blank", "noopener,noreferrer");
    inspectorActionMessage = `Opened: ${path}`;
  }

  async function runManifestAction(action: OperationActionManifestAction) {
    if (!selectedAsset) return;
    if (action.confirmation) {
      const approved = window.confirm(
        `${action.label}\n\nThis action is marked ${action.risk}. Continue?`,
      );
      if (!approved) return;
    }

    inspectorActionBusy = true;
    inspectorActionMessage = "";
    try {
      if (action.id.startsWith("open_")) {
        const routes: Record<string, string> = {
          open_radarr: "#/movies",
          open_sonarr: "#/series",
          open_qbittorrent: "#/qbittorrent",
          open_plex: "#/operations",
        };
        const target = routes[action.id] ?? "#/settings";
        window.open(
          `${window.location.origin}/${target}`,
          "_blank",
          "noopener,noreferrer",
        );
        inspectorActionMessage = `${action.label} launched.`;
        return;
      }

      if (
        action.id === "ignore_recommendation" ||
        action.id === "manual_review"
      ) {
        inspectorActionMessage = `${action.label} recorded for manual workflow.`;
        return;
      }

      if (!selectedRecommendation) {
        inspectorActionMessage = "This asset has no executable recommendation.";
        return;
      }

      const executableId = normalizeActionId(selectedRecommendation.action);
      if (action.id !== executableId) {
        inspectorActionMessage =
          "Action preview is available, but automation for this action is not yet wired.";
        return;
      }

      const result = await post_api<OperationWorkflowResponse>(
        `/api/operations/recommendations/${selectedRecommendation.id}/execute`,
        {},
      );
      workflowResults = [result, ...workflowResults].slice(0, 10);
      inspectorActionMessage =
        result.execution.message || `${action.label} completed.`;
      await Promise.all([loadWorkspace(), loadHistory()]);
    } catch (e: any) {
      inspectorActionMessage =
        e?.message ?? `Failed to execute ${action.label}`;
    } finally {
      inspectorActionBusy = false;
    }
  }

  function addArrayParams(
    params: URLSearchParams,
    key: string,
    values: number[],
  ) {
    for (const value of values) {
      params.append(key, String(value));
    }
  }

  function isExecutionTerminal(
    session: OperationExecutionSessionResponse | null,
  ): boolean {
    return (
      !!session && ["completed", "failed", "partial"].includes(session.status)
    );
  }

  function reconcileSelections(nextWorkspace: MieOperationsResponse | null) {
    if (!nextWorkspace?.workflow?.stages?.length) return;
    const assetStageById = new Map<string, string>();
    for (const stage of nextWorkspace.workflow.stages) {
      for (const asset of stage.assets ?? []) {
        assetStageById.set(asset.id, stage.key);
      }
    }
    const nextSelections: Record<string, Set<string>> = {};
    for (const ids of Object.values(stageSelections)) {
      for (const id of ids) {
        const stageKey = assetStageById.get(id);
        if (!stageKey) continue;
        if (!nextSelections[stageKey])
          nextSelections[stageKey] = new Set<string>();
        nextSelections[stageKey].add(id);
      }
    }
    stageSelections = nextSelections;
    if (selectedAssetId && !assetStageById.has(selectedAssetId)) {
      selectedAssetId = null;
    }
  }

  function loadPrefs() {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(PREFS_KEY);
      if (!raw) return;
      const prefs = JSON.parse(raw) as Partial<OperationsWorkspacePrefs>;
      search = prefs.search ?? search;
      sortBy = prefs.sortBy ?? sortBy;
      sortOrder = prefs.sortOrder ?? sortOrder;
      candidatesOnly = prefs.candidatesOnly ?? candidatesOnly;
      arrFilterIds = Array.isArray(prefs.arrFilterIds)
        ? prefs.arrFilterIds
        : arrFilterIds;
      decisionFilterIds = Array.isArray(prefs.decisionFilterIds)
        ? prefs.decisionFilterIds
        : decisionFilterIds;
      smartFilterIds = Array.isArray(prefs.smartFilterIds)
        ? prefs.smartFilterIds
        : smartFilterIds;
      selectedStage = prefs.selectedStage ?? selectedStage;
      selectedFilter = prefs.selectedFilter ?? selectedFilter;
      selectedMediaType = prefs.selectedMediaType ?? selectedMediaType;
      selectedReadiness = prefs.selectedReadiness ?? selectedReadiness;
      showCompleted = prefs.showCompleted ?? showCompleted;
      pageSize = prefs.pageSize ?? prefs.visibleAssetLimit ?? pageSize;
      currentPage = prefs.currentPage ?? currentPage;
      posterSize = prefs.posterSize ?? posterSize;
      displayMode = prefs.displayMode ?? displayMode;
    } catch {
      // ignore invalid local preferences
    }
  }

  function savePrefs() {
    if (typeof window === "undefined") return;
    const prefs: OperationsWorkspacePrefs = {
      search,
      sortBy,
      sortOrder,
      candidatesOnly,
      arrFilterIds,
      decisionFilterIds,
      smartFilterIds,
      selectedStage,
      selectedFilter,
      selectedMediaType,
      selectedReadiness,
      showCompleted,
      pageSize,
      currentPage,
      posterSize,
      displayMode,
    };
    window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  }

  function applyHashSelection() {
    const hash = window.location.hash || "";
    const queryIndex = hash.indexOf("?");
    if (queryIndex < 0) return;
    const params = new URLSearchParams(hash.slice(queryIndex + 1));
    const stageValue = params.get("stage") as WorkflowStageKey | null;
    if (stageValue) selectedStage = stageValue;
  }

  async function loadFilterCatalog() {
    try {
      filterCatalog = await get_api<MediaFilterCatalogResponse>(
        "/api/media/filters?media_types=movie&media_types=series",
      );
    } catch {
      filterCatalog = null;
    }
  }

  async function trackedGet<T>(url: string): Promise<T> {
    const startedAt = performance.now();
    const startedIso = new Date().toISOString();
    try {
      const response = await get_api<T>(url);
      networkLog = [
        ...networkLog.slice(-199),
        {
          method: "GET",
          url,
          status: 200,
          duration_ms: Math.round(performance.now() - startedAt),
          started_at: startedIso,
        },
      ];
      return response;
    } catch (error: any) {
      const message = String(error?.message ?? "Request failed");
      const statusMatch = message.match(/status\s(\d+)/i);
      const status = statusMatch ? Number(statusMatch[1]) : 0;
      networkLog = [
        ...networkLog.slice(-199),
        {
          method: "GET",
          url,
          status,
          duration_ms: Math.round(performance.now() - startedAt),
          started_at: startedIso,
        },
      ];
      throw error;
    }
  }

  async function loadWorkspace() {
    const startedAt = performance.now();
    const params = new URLSearchParams();
    params.set("candidates_only", String(candidatesOnly));
    addArrayParams(params, "arr_filter_ids", arrFilterIds);
    addArrayParams(params, "decision_filter_ids", decisionFilterIds);
    addArrayParams(params, "smart_filter_ids", smartFilterIds);
    const response = await trackedGet<MieOperationsResponse>(
      `/api/mie/operations?${params.toString()}`,
    );
    workspace = response;
    reconcileSelections(response);
    await tick();
    frontendRenderingMs = Math.round(performance.now() - startedAt);

    const imageStartedAt = performance.now();
    const images = Array.from(
      document.querySelectorAll("img[loading='lazy']"),
    ) as HTMLImageElement[];
    const pending = images.filter((img) => !img.complete);
    if (pending.length > 0) {
      await Promise.allSettled(
        pending.map(
          (img) =>
            new Promise<void>((resolve) => {
              const done = () => resolve();
              img.addEventListener("load", done, { once: true });
              img.addEventListener("error", done, { once: true });
            }),
        ),
      );
    }
    imageLoadingMs = Math.round(performance.now() - imageStartedAt);
  }

  async function loadHistory() {
    auditTrail = await trackedGet<OperationAuditListResponse>(
      "/api/operations/audit",
    );
    executionHistory = await trackedGet<OperationExecutionHistoryListResponse>(
      "/api/operations/executions/history",
    );
  }

  async function load() {
    loading = true;
    error = "";
    try {
      await Promise.all([loadFilterCatalog(), loadWorkspace(), loadHistory()]);
    } catch (e: any) {
      error = e?.message ?? "Failed to load operations workspace";
    } finally {
      loading = false;
    }
  }

  function setStageSelection(stageKey: string, next: Set<string>) {
    stageSelections = {
      ...stageSelections,
      [stageKey]: new Set(next),
    };
  }

  function toggleAsset(assetId: string, checked: boolean, shiftKey: boolean) {
    const stageKey = activeStage?.key ?? "download";
    const current = stageSelections[stageKey] ?? new Set<string>();
    const next = toggleAssetSelection(current, orderedFilteredIds, assetId, {
      checked,
      shift: shiftKey,
      lastClickedId: lastClickedByStage[stageKey] ?? null,
    });
    setStageSelection(stageKey, next);
    lastClickedByStage = { ...lastClickedByStage, [stageKey]: assetId };
  }

  function inspectAsset(assetId: string) {
    if (selectedAssetId !== assetId) {
      selectedAssetId = assetId;
      inspectorPreview = null;
      inspectorValidation = null;
      loadedCockpitKeys = new Set();
    }
    void ensureCockpitTabData(cockpitTab);
  }

  function selectAllFiltered() {
    const stageKey = activeStage?.key ?? "download";
    const next = new Set(selectedIdsInStage);
    for (const id of orderedFilteredIds) next.add(id);
    setStageSelection(stageKey, next);
  }

  function clearSelection() {
    stageSelections = {};
  }

  function toggleSelectDisplayed() {
    const stageKey = activeStage?.key ?? "download";
    const next = new Set(selectedIdsInStage);
    if (allDisplayedSelected) {
      for (const id of displayedIds) next.delete(id);
    } else {
      for (const id of displayedIds) next.add(id);
    }
    setStageSelection(stageKey, next);
  }

  async function refreshWorkspace() {
    workflowError = "";
    executionError = "";
    await Promise.all([loadWorkspace(), loadHistory()]);
  }

  async function bulkAction(mode: "preview" | "validate") {
    if (!selectedRecommendationIds.length) {
      workflowError = "Select at least one recommendation-backed asset first.";
      return;
    }
    workflowBusy = true;
    workflowMode = mode;
    workflowError = "";
    workflowResults = [];
    workflowProgress = {
      total: selectedRecommendationIds.length,
      completed: 0,
      failed: 0,
    };

    const results: OperationWorkflowResponse[] = [];
    for (const id of selectedRecommendationIds) {
      try {
        const response = await get_api<OperationWorkflowResponse>(
          `/api/operations/recommendations/${id}/${mode}`,
        );
        results.push(response);
      } catch (e: any) {
        workflowProgress = {
          ...workflowProgress,
          failed: workflowProgress.failed + 1,
        };
        results.push({
          recommendation_id: id,
          preview: {
            target_count: 0,
            estimated_recovery_bytes: 0,
            details: [e?.message ?? "Request failed"],
          },
          validation: {
            valid: false,
            checks: [
              {
                label: "Request",
                passed: false,
                detail: e?.message ?? "Request failed",
              },
            ],
          },
          execution: {
            executed: false,
            result: "failed",
            message: e?.message ?? "Request failed",
            operation_history_id: null,
          },
        });
      } finally {
        workflowProgress = {
          ...workflowProgress,
          completed: workflowProgress.completed + 1,
        };
      }
    }
    workflowResults = results;
    workflowBusy = false;
    workflowMode = null;
  }

  async function pollExecutionSession() {
    if (!executionSession?.session_id || executionPollInFlight) return;
    executionPollInFlight = true;
    try {
      const next = await get_api<OperationExecutionSessionResponse>(
        `/api/operations/executions/${executionSession.session_id}`,
      );
      executionSession = next;
      const patched = applyExecutionSessionToWorkspace(
        workspace,
        next,
        appliedExecutionIds,
        stageSelections,
      );
      workspace = patched.workspace as MieOperationsResponse | null;
      appliedExecutionIds = patched.appliedIds as Set<string>;
      stageSelections = patched.stageSelections as Record<string, Set<string>>;
      if (isExecutionTerminal(next)) {
        stopExecutionPolling();
        await loadHistory();
      }
    } catch (e: any) {
      executionError = e?.message ?? "Failed to update execution progress";
      stopExecutionPolling();
    } finally {
      executionPollInFlight = false;
    }
  }

  function stopExecutionPolling() {
    if (executionPollHandle) {
      clearInterval(executionPollHandle);
      executionPollHandle = null;
    }
  }

  function startExecutionPolling() {
    stopExecutionPolling();
    executionPollHandle = setInterval(() => {
      void pollExecutionSession();
    }, POLL_INTERVAL_MS);
  }

  async function beginExecution() {
    if (!selectedRecommendationIds.length) {
      executionError = "Select at least one recommendation-backed asset first.";
      return;
    }
    if (executionStarting || executionActive) {
      executionError = "Execution is already in progress.";
      return;
    }
    executionStarting = true;
    executionError = "";
    workflowError = "";
    appliedExecutionIds = new Set<string>();
    try {
      executionSession = await post_api<OperationExecutionSessionResponse>(
        "/api/operations/executions",
        { recommendation_ids: selectedRecommendationIds },
      );
      startExecutionPolling();
      void pollExecutionSession();
    } catch (e: any) {
      executionError = e?.message ?? "Failed to start execution session";
      executionSession = null;
      stopExecutionPolling();
    } finally {
      executionStarting = false;
    }
  }

  function handleToolbarBulkAction(key: string) {
    if (key === "preview") {
      void bulkAction("preview");
      return;
    }
    if (key === "validate") {
      void bulkAction("validate");
      return;
    }
    if (key === "execute") {
      void beginExecution();
      return;
    }
    if (key === "clear") {
      clearSelection();
    }
  }

  function toggleFilterSelection(
    source: "imported" | "decision" | "smart",
    filterId: number,
  ) {
    const update = (values: number[]) =>
      values.includes(filterId)
        ? values.filter((value) => value !== filterId)
        : [...values, filterId];
    if (source === "imported") arrFilterIds = update(arrFilterIds);
    if (source === "decision") decisionFilterIds = update(decisionFilterIds);
    if (source === "smart") smartFilterIds = update(smartFilterIds);
    void loadWorkspace();
  }

  function clearAllSharedFilters() {
    arrFilterIds = [];
    decisionFilterIds = [];
    smartFilterIds = [];
    void loadWorkspace();
  }

  function applySmartFilter(option: MediaFilterOptionResponse) {
    if (!option.filter_id) return;
    if (!smartFilterIds.includes(option.filter_id)) {
      smartFilterIds = [...smartFilterIds, option.filter_id];
      void loadWorkspace();
    }
  }

  function handleSearch(value: string) {
    search = value;
  }

  function onKeyboardShortcuts(event: KeyboardEvent) {
    if (!activeStage) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      event.preventDefault();
      selectAllFiltered();
      return;
    }
    if (event.key === "Escape") {
      clearSelection();
    }
  }

  function stageCardClass(key: WorkflowStageKey, active: boolean) {
    const base = "rounded-2xl border p-4 text-left transition";
    const state = active
      ? "border-primary bg-primary/10"
      : "border-border/70 bg-card/60 hover:bg-card";
    const accent =
      key === "cleanup"
        ? "ring-1 ring-orange-500/30"
        : key === "retention"
          ? "ring-1 ring-blue-500/30"
          : key === "completed"
            ? "ring-1 ring-emerald-500/30"
            : "";
    return `${base} ${state} ${accent}`;
  }

  function posterAlt(asset: OperationsWorkflowAsset) {
    return `${asset.title} poster`;
  }

  $effect(() => {
    savePrefs();
  });

  $effect(() => {
    if (!stageRows.some((row) => row.key === selectedStage) && stageRows[0]) {
      selectedStage = stageRows[0].key;
    }
  });

  $effect(() => {
    if (
      selectedFilter &&
      !stageFilterRows.some((row) => row.key === selectedFilter)
    ) {
      selectedFilter = null;
    }
  });

  $effect(() => {
    if (currentPage !== currentPageClamped) {
      currentPage = currentPageClamped;
    }
  });

  $effect(() => {
    search;
    sortBy;
    sortOrder;
    selectedFilter;
    selectedMediaType;
    selectedReadiness;
    selectedStage;
    pageSize;
    currentPage = 1;
  });

  $effect(() => {
    if (!selectedAssetId) return;
    void ensureCockpitTabData(cockpitTab);
  });

  onMount(() => {
    const originalLog = console.log;
    const originalWarn = console.warn;
    const originalError = console.error;
    const originalInfo = console.info;

    const appendConsole = (level: string, args: any[]) => {
      const message = args
        .map((value) =>
          typeof value === "string" ? value : JSON.stringify(value),
        )
        .join(" ");
      consoleLog = [
        ...consoleLog.slice(-399),
        { level, message, at: new Date().toISOString() },
      ];
    };

    console.log = (...args: any[]) => {
      appendConsole("log", args);
      originalLog(...args);
    };
    console.warn = (...args: any[]) => {
      appendConsole("warn", args);
      originalWarn(...args);
    };
    console.error = (...args: any[]) => {
      appendConsole("error", args);
      originalError(...args);
    };
    console.info = (...args: any[]) => {
      appendConsole("info", args);
      originalInfo(...args);
    };

    loadPrefs();
    applyHashSelection();
    void load();

    return () => {
      console.log = originalLog;
      console.warn = originalWarn;
      console.error = originalError;
      console.info = originalInfo;
    };
  });

  onDestroy(() => {
    stopExecutionPolling();
  });
</script>

<svelte:window onkeydown={onKeyboardShortcuts} />

<div class="p-2.5 md:p-8">
  <div class="mx-auto max-w-[1520px] space-y-6">
    <header
      class="rounded-[2rem] border border-border/70 bg-gradient-to-br from-card via-background to-secondary/20 p-6 shadow-xl shadow-black/10"
    >
      <p class="text-xs uppercase tracking-[0.3em] text-muted-foreground">
        Operations Workspace
      </p>
      <h1 class="text-4xl font-black tracking-tight text-foreground">
        Media Lifecycle Console
      </h1>
      <p class="mt-2 max-w-3xl text-sm text-muted-foreground">
        Execute lifecycle work without losing context. Preview, validate, and
        run bulk actions while the workspace stays live.
      </p>
    </header>

    {#if loading}
      <div
        class="rounded-xl border border-border bg-card p-6 text-muted-foreground"
      >
        Loading operations workspace...
      </div>
    {:else if error}
      <div
        class="rounded-xl border border-destructive/40 bg-destructive/10 p-6 text-destructive"
      >
        {error}
      </div>
    {:else}
      <WorkspaceToolbar
        searchQuery={search}
        searchPlaceholder="Search workflow assets, reasons, and status..."
        {sortBy}
        {sortByOptions}
        {sortOrder}
        {candidatesOnly}
        {filterCatalog}
        importedFilterIds={arrFilterIds}
        {decisionFilterIds}
        {smartFilterIds}
        {selectedFilterOptions}
        perPage={pageSize}
        {posterSize}
        viewMode={displayMode}
        viewModes={["grid", "list"]}
        selectedCount={totalSelectedCount}
        displayedCount={displayedAssets.length}
        totalCount={filteredAssets.length}
        showSelectDisplayed={true}
        selectDisplayedChecked={allDisplayedSelected}
        selectDisplayedIndeterminate={someDisplayedSelected}
        onToggleSelectDisplayed={toggleSelectDisplayed}
        bulkActions={toolbarActions}
        onSearchInput={handleSearch}
        onSortByChange={(value) => (sortBy = value as SortBy)}
        onSortOrderChange={(value) => (sortOrder = value)}
        onCandidatesOnlyChange={(value) => {
          candidatesOnly = value;
          void loadWorkspace();
        }}
        onToggleFilterSelection={toggleFilterSelection}
        onOpenFilterManager={() => {}}
        onOpenSmartFilterDialog={() => {}}
        onApplySmartFilter={applySmartFilter}
        onClearAllFilters={clearAllSharedFilters}
        onPerPageChange={(value) => {
          pageSize = value;
          currentPage = 1;
        }}
        onPosterSizeChange={(value) => (posterSize = value)}
        onViewModeChange={(value) => (displayMode = value as ViewMode)}
        onBulkAction={handleToolbarBulkAction}
      />

      <section class="rounded-2xl border border-border/70 bg-card/60 p-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-sm font-semibold text-foreground">
            Performance Profile
          </h2>
          <span
            class={`rounded-full border px-2 py-0.5 text-xs ${performanceProfile.backend_api_ms < 5000 ? "border-emerald-500/60 text-emerald-300" : "border-amber-500/60 text-amber-300"}`}
          >
            Backend API {performanceProfile.backend_api_ms} ms
          </span>
        </div>
        <div class="mt-3 grid gap-2 text-xs sm:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-lg border border-border/60 bg-background/60 p-2">
            <p class="text-muted-foreground">Filesystem Analysis</p>
            <p class="mt-1 font-medium text-foreground">
              {performanceProfile.filesystem_analysis_ms} ms
            </p>
          </div>
          <div class="rounded-lg border border-border/60 bg-background/60 p-2">
            <p class="text-muted-foreground">Artwork Loading</p>
            <p class="mt-1 font-medium text-foreground">
              {performanceProfile.artwork_loading_ms} ms
            </p>
          </div>
          <div class="rounded-lg border border-border/60 bg-background/60 p-2">
            <p class="text-muted-foreground">Identity Graph</p>
            <p class="mt-1 font-medium text-foreground">
              {performanceProfile.identity_graph_ms} ms
            </p>
          </div>
          <div class="rounded-lg border border-border/60 bg-background/60 p-2">
            <p class="text-muted-foreground">Torrent Intelligence</p>
            <p class="mt-1 font-medium text-foreground">
              {performanceProfile.torrent_intelligence_ms} ms
            </p>
          </div>
          <div class="rounded-lg border border-border/60 bg-background/60 p-2">
            <p class="text-muted-foreground">Narrative Generation</p>
            <p class="mt-1 font-medium text-foreground">
              {performanceProfile.narrative_generation_ms} ms
            </p>
          </div>
          <div class="rounded-lg border border-border/60 bg-background/60 p-2">
            <p class="text-muted-foreground">Frontend Rendering</p>
            <p class="mt-1 font-medium text-foreground">
              {frontendRenderingMs} ms
            </p>
          </div>
          <div class="rounded-lg border border-border/60 bg-background/60 p-2">
            <p class="text-muted-foreground">Image Loading</p>
            <p class="mt-1 font-medium text-foreground">{imageLoadingMs} ms</p>
          </div>
          <div class="rounded-lg border border-border/60 bg-background/60 p-2">
            <p class="text-muted-foreground">Bundle Schema</p>
            <p class="mt-1 font-medium text-foreground">
              mmr.support-bundle.v1
            </p>
          </div>
        </div>
      </section>

      <section class="space-y-3">
        <div class="flex items-center justify-between gap-3">
          <h2 class="text-lg font-semibold text-foreground">Workflow Lanes</h2>
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40"
              onclick={refreshWorkspace}
              disabled={workflowBusy || executionActive}
            >
              Refresh Changed Data
            </button>
            <button
              type="button"
              class={`rounded-full border px-3 py-1.5 text-xs ${showCompleted ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
              onclick={() => (showCompleted = !showCompleted)}
            >
              {showCompleted ? "Hide Completed" : "Show Completed"}
            </button>
          </div>
        </div>

        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
          {#each stageRows as stage}
            {@const stats = stageStats(stage.assets)}
            <button
              type="button"
              class={stageCardClass(stage.key, selectedStage === stage.key)}
              onclick={() => {
                selectedStage = stage.key;
              }}
            >
              <p
                class="text-xs uppercase tracking-[0.18em] text-muted-foreground"
              >
                {stage.title}
              </p>
              <p class="mt-2 text-2xl font-black text-foreground">
                {stage.count}
              </p>
              <p class="mt-1 text-xs text-muted-foreground">
                {stage.description}
              </p>
              <div
                class="mt-3 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground"
              >
                <span>Ready {stats.ready}</span>
                <span>Blocked {stats.blocked}</span>
                <span>Needs Review {stats.needsReview}</span>
                <span>Warnings {stats.warnings}</span>
              </div>
            </button>
          {/each}
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-foreground">Stage Filters</h2>

        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class={`rounded-full border px-3 py-1.5 text-xs ${selectedFilter === null ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
            onclick={() => (selectedFilter = null)}
          >
            All ({activeStage?.count ?? 0})
          </button>
          {#each stageFilterRows as row}
            <button
              type="button"
              class={`rounded-full border px-3 py-1.5 text-xs ${selectedFilter === row.key ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
              onclick={() => (selectedFilter = row.key)}
            >
              {row.title} ({row.count})
            </button>
          {/each}
        </div>

        <div class="flex flex-wrap gap-2">
          {#each ["all", "movies", "series", "anime", "collections"] as option}
            <button
              type="button"
              class={`rounded-full border px-3 py-1.5 text-xs ${selectedMediaType === option ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
              onclick={() => (selectedMediaType = option as LocalMediaFilter)}
            >
              {option === "all"
                ? "All Media"
                : option[0].toUpperCase() + option.slice(1)}
            </button>
          {/each}
        </div>

        <div class="flex flex-wrap gap-2">
          {#each [["all", "All"], ["ready", "Ready"], ["blocked", "Blocked"], ["needs_review", "Needs Review"], ["high_confidence", "High Confidence"], ["low_confidence", "Low Confidence"]] as [key, label]}
            <button
              type="button"
              class={`rounded-full border px-3 py-1.5 text-xs ${selectedReadiness === key ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
              onclick={() => (selectedReadiness = key as LocalReadinessFilter)}
            >
              {label}
            </button>
          {/each}
        </div>
      </section>

      <section
        class="sticky top-2 z-20 rounded-2xl border border-border/70 bg-background/95 p-3 shadow backdrop-blur"
      >
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="font-semibold text-foreground">Selected:</span>
          <span
            class="rounded-full border border-border px-2 py-1 text-xs text-foreground"
            >{selectedAssets.length} Visible</span
          >
          <span
            class="rounded-full border border-border px-2 py-1 text-xs text-muted-foreground"
            >Recommendation-backed: {selectedRecommendationIds.length}</span
          >
          <span
            class="rounded-full border border-border px-2 py-1 text-xs text-muted-foreground"
            >Lane: {activeStage?.title ?? "Workflow"}</span
          >

          <button
            type="button"
            class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40"
            onclick={selectAllFiltered}>Select All</button
          >
          <button
            type="button"
            class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40"
            onclick={clearSelection}>Clear Selection</button
          >
          <button
            type="button"
            class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40"
            onclick={() => bulkAction("preview")}
            disabled={workflowBusy || executionActive}>Preview</button
          >
          <button
            type="button"
            class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40"
            onclick={() => bulkAction("validate")}
            disabled={workflowBusy || executionActive}>Validate</button
          >
          <button
            type="button"
            class="rounded-full border border-primary bg-primary/10 px-3 py-1.5 text-xs text-primary hover:bg-primary/20"
            onclick={beginExecution}
            disabled={workflowBusy || executionActive}>Execute</button
          >
        </div>

        {#if workflowBusy || workflowResults.length > 0 || workflowError || executionSession || executionError}
          <div
            class="mt-3 rounded-xl border border-border/60 bg-card/60 p-3 text-xs"
            transition:slide
          >
            {#if workflowResults.length > 0}
              <div
                class="flex flex-wrap items-center gap-2 text-muted-foreground"
              >
                <span>Assets Selected {selectedRecommendationIds.length}</span>
                <span>Validated {bulkSummary.validated}</span>
                <span>Blocked {bulkSummary.blocked}</span>
                <span>Warnings {bulkSummary.warnings}</span>
                <span>Expected Success {bulkSummary.expectedSuccess}</span>
                <span
                  >Estimated Recovery {formatFileSize(
                    bulkSummary.estimatedRecovery,
                  )}</span
                >
              </div>
            {/if}

            {#if workflowBusy}
              <div class="mt-3 space-y-1">
                <p class="text-muted-foreground">
                  {workflowMode === "preview"
                    ? "Building preview..."
                    : "Running validation..."}
                </p>
                <div
                  class="h-2 w-full overflow-hidden rounded-full bg-secondary/50"
                >
                  <div
                    class="h-full bg-primary transition-all"
                    style={`width:${workflowProgressPercent}%`}
                  ></div>
                </div>
                <p class="text-muted-foreground">
                  Completed {workflowProgress.completed} • Remaining {Math.max(
                    0,
                    workflowProgress.total - workflowProgress.completed,
                  )} • Failed {workflowProgress.failed}
                </p>
              </div>
            {/if}

            {#if executionSession}
              <div class="mt-3 space-y-2" in:fade>
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p class="text-sm font-semibold text-foreground">
                      {executionSession.status === "completed"
                        ? "Execution Complete"
                        : executionSession.status === "partial"
                          ? "Execution Complete With Warnings"
                          : executionSession.status === "failed"
                            ? "Execution Failed"
                            : executionSession.current_step_label ||
                              "Executing..."}
                    </p>
                    <p class="text-muted-foreground">
                      {executionSession.current_asset_title ||
                        "Workspace remains live while operations continue."}
                    </p>
                  </div>
                  <div class="flex flex-wrap gap-2 text-muted-foreground">
                    <span
                      >{executionSession.completed} / {executionSession.total} Assets</span
                    >
                    <span
                      >Elapsed {formatDuration(
                        executionSession.elapsed_ms,
                      )}</span
                    >
                    {#if executionSession.estimated_remaining_ms !== null}
                      <span
                        >ETA {formatDuration(
                          executionSession.estimated_remaining_ms,
                        )}</span
                      >
                    {/if}
                  </div>
                </div>

                <div
                  class="h-2 w-full overflow-hidden rounded-full bg-secondary/50"
                >
                  <div
                    class="h-full bg-primary transition-all duration-300"
                    style={`width:${executionProgressPercent}%`}
                  ></div>
                </div>

                <p class="text-muted-foreground">
                  Completed {executionSession.completed} • Remaining {executionSession.remaining}
                  • Failed {executionSession.failed} • Warnings {executionSession.warnings}
                </p>
              </div>
            {/if}

            {#if workflowError}
              <p class="mt-2 text-destructive">{workflowError}</p>
            {/if}
            {#if executionError}
              <p class="mt-2 text-destructive">{executionError}</p>
            {/if}
          </div>
        {/if}
      </section>

      <section class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div class="space-y-3">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h2 class="text-lg font-semibold text-foreground">
              Assets in {activeStage?.title ?? "Stage"}
            </h2>
            <p class="text-xs text-muted-foreground">
              Displaying {filteredAssets.length === 0 ? 0 : pageStartIndex + 1}
              -{pageEndIndexExclusive} of {filteredAssets.length} assets in {stageTitle(
                activeStage?.key,
              )}
            </p>
          </div>

          {#if filteredAssets.length > 0}
            <div
              class="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border/60 bg-card/40 px-3 py-2 text-xs"
            >
              <div class="text-muted-foreground">
                Page {currentPageClamped} of {totalPages}
              </div>
              <div class="flex flex-wrap items-center gap-1">
                <button
                  type="button"
                  class="rounded-full border border-border px-2 py-1 disabled:opacity-50"
                  onclick={() => setPage(currentPageClamped - 1)}
                  disabled={currentPageClamped <= 1}
                >
                  Previous
                </button>
                {#if pageNumbers[0] > 1}
                  <button
                    type="button"
                    class="rounded-full border border-border px-2 py-1"
                    onclick={() => setPage(1)}
                  >
                    1
                  </button>
                  {#if pageNumbers[0] > 2}
                    <span class="px-1 text-muted-foreground">...</span>
                  {/if}
                {/if}
                {#each pageNumbers as page}
                  <button
                    type="button"
                    class={`rounded-full border px-2 py-1 ${page === currentPageClamped ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
                    onclick={() => setPage(page)}
                  >
                    {page}
                  </button>
                {/each}
                {#if pageNumbers[pageNumbers.length - 1] < totalPages}
                  {#if pageNumbers[pageNumbers.length - 1] < totalPages - 1}
                    <span class="px-1 text-muted-foreground">...</span>
                  {/if}
                  <button
                    type="button"
                    class="rounded-full border border-border px-2 py-1"
                    onclick={() => setPage(totalPages)}
                  >
                    {totalPages}
                  </button>
                {/if}
                <button
                  type="button"
                  class="rounded-full border border-border px-2 py-1 disabled:opacity-50"
                  onclick={() => setPage(currentPageClamped + 1)}
                  disabled={currentPageClamped >= totalPages}
                >
                  Next
                </button>
              </div>
            </div>
          {/if}

          {#if filteredAssets.length === 0}
            <p
              class="rounded-2xl border border-border/70 bg-card/60 p-4 text-sm text-muted-foreground"
            >
              No assets for this stage/filter combination.
            </p>
          {:else}
            <div
              class={displayMode === "list"
                ? "space-y-3"
                : "grid gap-3 md:grid-cols-2 2xl:grid-cols-3"}
            >
              {#each displayedAssets as asset, index (`${asset.id}:${asset.current_stage ?? ""}:${index}`)}
                {@const hasPoster = !!asset.poster_url}
                <article
                  animate:flip={{ duration: 220 }}
                  class={`rounded-2xl border bg-card/60 p-3 transition ${selectedAssetId === asset.id ? "border-primary shadow-lg shadow-primary/10" : "border-border/70 hover:bg-card"}`}
                >
                  <div class="mb-2 flex items-start justify-between gap-2">
                    <label
                      class="inline-flex items-center gap-2 text-xs text-muted-foreground"
                    >
                      <input
                        type="checkbox"
                        aria-label={`Select ${asset.title}`}
                        checked={selectedIdsInStage.has(asset.id)}
                        onclick={(event) =>
                          toggleAsset(
                            asset.id,
                            (event.currentTarget as HTMLInputElement).checked,
                            (event as MouseEvent).shiftKey,
                          )}
                      />
                      Select
                    </label>
                    <button
                      type="button"
                      class="text-xs text-primary underline-offset-2 hover:underline"
                      onclick={() => inspectAsset(asset.id)}
                    >
                      Inspect
                    </button>
                  </div>

                  <button
                    type="button"
                    class={displayMode === "list"
                      ? "grid w-full gap-3 text-left md:grid-cols-[140px_minmax(0,1fr)]"
                      : "w-full text-left"}
                    onclick={() => inspectAsset(asset.id)}
                    aria-label={`Open inspector for ${asset.title}`}
                  >
                    {#if hasPoster}
                      <img
                        src={asset.poster_url ?? ""}
                        alt={posterAlt(asset)}
                        class="w-full rounded-xl object-cover"
                        style={`height:${Math.max(180, Math.round(posterSize * 1.6))}px`}
                        loading="lazy"
                      />
                    {:else}
                      <div
                        class="flex w-full flex-col items-center justify-center rounded-xl border border-dashed border-border bg-secondary/30 px-3 text-center"
                        style={`height:${Math.max(180, Math.round(posterSize * 1.6))}px`}
                      >
                        <p class="text-sm font-semibold text-foreground">
                          Missing Artwork
                        </p>
                        <p class="mt-1 text-xs text-muted-foreground">
                          Artwork Repair Available
                        </p>
                      </div>
                    {/if}

                    <div class="mt-3 space-y-2 md:mt-0">
                      <div
                        class="flex flex-wrap items-start justify-between gap-2"
                      >
                        <div>
                          <h3
                            class="line-clamp-2 text-base font-semibold text-foreground"
                          >
                            {asset.title}
                          </h3>
                          <p class="text-xs text-muted-foreground">
                            {narrativeSummary(asset)}
                          </p>
                        </div>
                        <div class="flex flex-wrap items-center gap-2 text-xs">
                          <span
                            class={`rounded-full border px-2 py-0.5 ${narrativeOutcomeClass(asset)}`}
                            >{narrativeOutcomeLabel(asset)}</span
                          >
                          <span
                            class={`rounded-full border px-2 py-0.5 ${workflowOutcomeClass(asset)}`}
                            >{workflowOutcomeLabel(asset)}</span
                          >
                          <span
                            class="rounded-full border border-border px-2 py-0.5 text-muted-foreground"
                            >Risk {riskLabel(asset.risk_level)}</span
                          >
                        </div>
                      </div>

                      <div class="rounded-lg bg-background/70 p-2">
                        <p
                          class="text-xs uppercase tracking-[0.14em] text-muted-foreground"
                        >
                          What
                        </p>
                        <p class="mt-1 text-sm font-semibold text-foreground">
                          {narrativeSummary(asset)}
                        </p>
                        <p class="mt-1 text-xs text-muted-foreground">
                          {workflowSummary(asset)}
                        </p>
                      </div>

                      <div>
                        <div class="flex items-center justify-between text-xs">
                          <span class="text-muted-foreground">Confidence</span>
                          <span class="text-foreground"
                            >{confidenceLabel(asset.confidence)} confidence</span
                          >
                        </div>
                        <div
                          class="mt-1 h-2 overflow-hidden rounded-full bg-secondary/50"
                        >
                          <div
                            class={`h-full ${confidenceBarClass(asset.confidence)}`}
                            style={`width:${asset.confidence ?? 0}%`}
                          ></div>
                        </div>
                        <p class="mt-1 text-[11px] text-muted-foreground">
                          {confidenceSummary(asset.confidence)}
                        </p>
                      </div>
                    </div>
                  </button>
                </article>
              {/each}
            </div>
          {/if}
        </div>

        <aside class="rounded-2xl border border-border/70 bg-card/60 p-4">
          <h2 class="text-lg font-semibold text-foreground">
            Operational Cockpit
          </h2>
          {#if selectedAsset}
            <div class="mt-3 space-y-3 text-sm" in:fade>
              <div class="flex flex-wrap items-center justify-between gap-2">
                <p class="text-xs text-muted-foreground">
                  Export operational evidence for support, bugs, and design
                  review.
                </p>
                <div class="flex flex-wrap gap-2">
                  <button
                    type="button"
                    class="rounded-full border border-border px-3 py-1 text-xs text-foreground hover:bg-secondary/40 disabled:opacity-50"
                    onclick={exportSnapshot}
                    disabled={exporting !== null}
                  >
                    {exporting === "snapshot"
                      ? "Exporting Snapshot..."
                      : "Snapshot"}
                  </button>
                  <button
                    type="button"
                    class="rounded-full border border-primary px-3 py-1 text-xs text-primary hover:bg-primary/10 disabled:opacity-50"
                    onclick={exportSupportBundle}
                    disabled={exporting !== null}
                  >
                    {exporting === "bundle"
                      ? "Exporting Support Bundle..."
                      : "Support Bundle"}
                  </button>
                </div>
              </div>

              <div class="flex flex-wrap gap-2">
                {#each cockpitTabs as tab}
                  <button
                    type="button"
                    class={`rounded-full border px-2.5 py-1 text-[11px] ${cockpitTab === tab.key ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
                    onclick={() => selectCockpitTab(tab.key)}
                  >
                    {tab.label}
                  </button>
                {/each}
              </div>

              {#if inspectorActionMessage}
                <p
                  class="rounded-lg border border-border/60 bg-background/60 px-3 py-2 text-xs text-muted-foreground"
                >
                  {inspectorActionMessage}
                </p>
              {/if}

              {#if inspectorTabBusy}
                <p class="text-xs text-muted-foreground">Loading tab data...</p>
              {/if}

              {#if cockpitTab === "overview"}
                <div class="space-y-3">
                  {#if selectedAsset.poster_url}
                    <img
                      src={selectedAsset.poster_url}
                      alt={posterAlt(selectedAsset)}
                      class="h-72 w-full rounded-xl object-cover"
                      loading="lazy"
                    />
                  {:else}
                    <div
                      class="flex h-72 w-full items-center justify-center rounded-xl border border-dashed border-border bg-secondary/20 text-xs text-muted-foreground"
                    >
                      Artwork unavailable
                    </div>
                  {/if}
                  <div
                    class="rounded-lg border border-border/60 bg-background/60 p-3 text-xs text-muted-foreground"
                  >
                    <p class="text-[11px] uppercase tracking-[0.14em]">What</p>
                    <p class="mt-2 text-sm text-foreground">
                      {narrativeSummary(selectedAsset)}
                    </p>
                    <p class="mt-2">{workflowSummary(selectedAsset)}</p>
                  </div>
                  <div class="grid gap-2 text-xs sm:grid-cols-2">
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-3"
                    >
                      <p
                        class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                      >
                        Current Location
                      </p>
                      <p class="mt-2 break-all font-medium text-foreground">
                        {narrativeWhere(selectedAsset)?.current_path ??
                          "Unavailable"}
                      </p>
                    </div>
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-3"
                    >
                      <p
                        class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                      >
                        Expected Location
                      </p>
                      <p class="mt-2 break-all font-medium text-foreground">
                        {narrativeWhere(selectedAsset)?.expected_path ??
                          selectedAsset.expected_destination ??
                          "Unavailable"}
                      </p>
                    </div>
                  </div>
                  <div class="grid gap-2 text-xs sm:grid-cols-3">
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-3"
                    >
                      <p
                        class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                      >
                        Why
                      </p>
                      <p class="mt-2 text-muted-foreground">
                        {narrativeLines(selectedAsset, "why")[0] ??
                          "Operational evidence available."}
                      </p>
                    </div>
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-3"
                    >
                      <p
                        class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                      >
                        Impact
                      </p>
                      <p class="mt-2 text-muted-foreground">
                        {narrativeLines(selectedAsset, "impact")[0] ??
                          "No action required."}
                      </p>
                    </div>
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-3"
                    >
                      <p
                        class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                      >
                        Next
                      </p>
                      <p class="mt-2 text-muted-foreground">
                        {narrativeLines(selectedAsset, "next")[0] ??
                          "No action required."}
                      </p>
                    </div>
                  </div>
                  <details
                    class="rounded-lg border border-border/60 bg-background/60 p-3 text-xs"
                  >
                    <summary
                      class="cursor-pointer text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                    >
                      Technical Details
                    </summary>
                    <div class="mt-3 grid gap-2 sm:grid-cols-3">
                      <div class="space-y-1 text-muted-foreground">
                        <p class="font-medium text-foreground">Why</p>
                        {#each narrativeLines(selectedAsset, "why") as line}
                          <p>{line}</p>
                        {/each}
                      </div>
                      <div class="space-y-1 text-muted-foreground">
                        <p class="font-medium text-foreground">Impact</p>
                        {#each narrativeLines(selectedAsset, "impact") as line}
                          <p>{line}</p>
                        {/each}
                      </div>
                      <div class="space-y-1 text-muted-foreground">
                        <p class="font-medium text-foreground">Next</p>
                        {#each narrativeLines(selectedAsset, "next") as line}
                          <p>{line}</p>
                        {/each}
                      </div>
                    </div>
                    <div
                      class="mt-3 rounded-md border border-border/50 bg-background/70 p-2 text-muted-foreground"
                    >
                      <p>Raw stage: {selectedAsset.current_stage}</p>
                      <p>Raw status: {selectedAsset.current_status}</p>
                      <p>
                        Torrent state: {selectedAsset.torrent_state ??
                          "Unavailable"}
                      </p>
                      <p>
                        Import state: {selectedAsset.import_state ??
                          "Unavailable"}
                      </p>
                      <p>
                        Retention policy: {selectedAsset.retention_policy ??
                          "Unavailable"}
                      </p>
                      <p>Confidence score: {selectedAsset.confidence ?? 0}%</p>
                    </div>
                  </details>
                  <div class="grid grid-cols-2 gap-2 text-xs">
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-2"
                    >
                      <p class="text-muted-foreground">Title</p>
                      <p class="font-medium text-foreground">
                        {selectedAsset.title}
                      </p>
                    </div>
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-2"
                    >
                      <p class="text-muted-foreground">Year</p>
                      <p class="font-medium text-foreground">
                        {selectedAsset.year ?? "Unknown"}
                      </p>
                    </div>
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-2"
                    >
                      <p class="text-muted-foreground">Media Type</p>
                      <p class="font-medium text-foreground">
                        {selectedAsset.media_type ?? "Unknown"}
                      </p>
                    </div>
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-2"
                    >
                      <p class="text-muted-foreground">Lifecycle</p>
                      <p class="font-medium text-foreground">
                        {selectedAsset.current_stage}
                      </p>
                    </div>
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-2"
                    >
                      <p class="text-muted-foreground">
                        {assetActionHeading(selectedAsset)}
                      </p>
                      <p class="font-medium text-foreground">
                        {assetActionLabel(selectedAsset)}
                      </p>
                    </div>
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-2"
                    >
                      <p class="text-muted-foreground">Confidence</p>
                      <p class="font-medium text-foreground">
                        {confidenceLabel(selectedAsset.confidence)} confidence
                      </p>
                      <p class="mt-1 text-muted-foreground">
                        {confidenceSummary(selectedAsset.confidence)}
                      </p>
                    </div>
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-2"
                    >
                      <p class="text-muted-foreground">Health Status</p>
                      <p class="font-medium text-foreground">
                        {selectedAsset.current_status}
                      </p>
                    </div>
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-2"
                    >
                      <p class="text-muted-foreground">Current Owner</p>
                      <p class="font-medium text-foreground">
                        {selectedAsset.policy_name ?? "Unavailable"}
                      </p>
                    </div>
                  </div>
                </div>
              {/if}

              {#if cockpitTab === "status"}
                <div class="space-y-2 text-xs">
                  <div
                    class="rounded-lg border border-border/60 bg-background/60 px-3 py-2"
                  >
                    <p class="text-muted-foreground">What</p>
                    <p class="mt-1 font-medium text-foreground">
                      {narrativeSummary(selectedAsset)}
                    </p>
                    <p class="mt-2 text-muted-foreground">
                      {workflowSummary(selectedAsset)}
                    </p>
                  </div>
                  <div
                    class="rounded-lg border border-border/60 bg-background/60 px-3 py-2"
                  >
                    <p class="text-muted-foreground">Torrent</p>
                    <p class="mt-1 font-medium text-foreground">
                      {torrentOperationalState(selectedAsset.torrent_state)
                        .label}
                    </p>
                    <p class="mt-1 text-muted-foreground">
                      {torrentOperationalState(selectedAsset.torrent_state)
                        .what}
                    </p>
                    <p class="mt-1 text-muted-foreground">
                      {torrentOperationalState(selectedAsset.torrent_state)
                        .action}
                    </p>
                  </div>
                  {#each [["Import", selectedAsset.import_state || "Unavailable"], ["Filesystem", selectedLocations.some((row) => row.path) ? "Healthy" : "Unavailable"], ["Identity", selectedAsset.graph_references.length > 0 ? "Healthy" : "Unavailable"], ["Metadata", selectedRecommendation ? "Pending" : "Unavailable"], ["Artwork", selectedAsset.poster_url ? "Healthy" : "Warning"], ["Collections", selectedAsset.policy_name ? "Pending" : "Unavailable"], ["Retention", selectedAsset.retention_policy || "Unavailable"], ["Cleanup", selectedAsset.current_stage === "cleanup" ? "Running" : "Pending"]] as [label, value]}
                    <div
                      class="flex items-center justify-between rounded-lg border border-border/60 bg-background/60 px-3 py-2"
                    >
                      <span class="text-muted-foreground">{label}</span>
                      <span class="font-medium text-foreground">{value}</span>
                    </div>
                  {/each}
                </div>
              {/if}

              {#if cockpitTab === "files"}
                <div class="space-y-2 text-xs">
                  <div
                    class="rounded-lg border border-border/60 bg-background/60 px-3 py-2 text-left text-muted-foreground"
                  >
                    <p class="font-medium text-foreground">Compare Files</p>
                    <p class="mt-1">{fileComparisonSummary}</p>
                  </div>

                  {#if selectedLocations.length > 0}
                    {#each selectedLocations as row}
                      <div
                        class="rounded-lg border border-border/60 bg-background/60 p-3"
                      >
                        <div class="flex items-center justify-between gap-2">
                          <p class="font-medium text-foreground">{row.label}</p>
                          <span
                            class="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground"
                            >{fileOperationalStatus(row)}</span
                          >
                        </div>

                        <div
                          class="mt-2 rounded-md border border-border/50 bg-background/70 p-2"
                        >
                          <p
                            class="text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
                          >
                            Location
                          </p>
                          <p class="mt-1 break-all font-medium text-foreground">
                            {filePathDisplay(row)}
                          </p>
                        </div>

                        <div class="mt-2 grid gap-2 sm:grid-cols-2">
                          <div
                            class="rounded-md border border-border/40 bg-background/70 p-2"
                          >
                            <p
                              class="text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
                            >
                              Expected Destination
                            </p>
                            <p
                              class="mt-1 break-all font-medium text-foreground"
                            >
                              {row.expected_destination ?? "Unavailable"}
                            </p>
                          </div>
                          <div
                            class="rounded-md border border-border/40 bg-background/70 p-2"
                          >
                            <p
                              class="text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
                            >
                              Import Eligibility
                            </p>
                            <p class="mt-1 font-medium text-foreground">
                              {row.import_eligibility ?? "Unavailable"}
                            </p>
                          </div>
                        </div>

                        <p class="mt-2 text-muted-foreground">
                          {fileRecommendedAction(row)}
                        </p>
                        <p class="mt-1 text-muted-foreground">
                          {row.explanation ??
                            "No additional filesystem explanation is available."}
                        </p>
                        <p class="mt-1 text-muted-foreground">
                          Source: {row.source ?? "Unavailable"}
                        </p>

                        <div class="mt-2 flex flex-wrap gap-1">
                          <button
                            type="button"
                            class="rounded-full border border-border px-2 py-1"
                            onclick={() => openFilesystemPath(row.path)}
                            >Open Folder</button
                          >
                          <button
                            type="button"
                            class="rounded-full border border-border px-2 py-1"
                            onclick={() => copyPath(row.path)}>Copy Path</button
                          >
                          <button
                            type="button"
                            class="rounded-full border border-border px-2 py-1"
                            onclick={() => openFilesystemPath(row.path)}
                            >Reveal File</button
                          >
                        </div>

                        <details
                          class="mt-2 rounded-md border border-border/40 bg-background/70 p-2"
                        >
                          <summary
                            class="cursor-pointer text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground"
                          >
                            Advanced Details
                          </summary>
                          <div
                            class="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3"
                          >
                            {#each fileEvidenceAdvancedFields(row) as field}
                              <div
                                class="rounded-md border border-border/40 bg-background/80 p-2"
                              >
                                <p
                                  class="text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
                                >
                                  {field.label}
                                </p>
                                <p
                                  class="mt-1 break-all font-medium text-foreground"
                                >
                                  {field.value}
                                </p>
                              </div>
                            {/each}
                          </div>
                        </details>
                      </div>
                    {/each}
                  {:else}
                    <p class="text-muted-foreground">
                      No filesystem evidence is currently indexed for this
                      asset.
                    </p>
                  {/if}
                </div>
              {/if}

              {#if cockpitTab === "applications"}
                <div class="space-y-2 text-xs">
                  {#each selectedApplications as row}
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-2"
                    >
                      <p class="text-muted-foreground">{row.role}</p>
                      <p class="font-medium text-foreground">
                        {row.application}
                      </p>
                      <p class="mt-1 text-muted-foreground">
                        {row.status === "linked"
                          ? (row.reference ?? "Linked")
                          : "Unavailable"}
                      </p>
                      <p class="mt-1 text-muted-foreground">
                        {row.explanation}
                      </p>
                    </div>
                  {/each}
                  <div class="flex flex-wrap gap-1">
                    {#each selectedManifestActions.filter((row) => row.category === "external" || row.presentation === "secondary") as action}
                      <button
                        type="button"
                        class="rounded-full border border-border px-2 py-1"
                        onclick={() => runManifestAction(action)}
                        disabled={inspectorActionBusy}>{action.label}</button
                      >
                    {/each}
                  </div>
                </div>
              {/if}

              {#if cockpitTab === "relationships"}
                <div class="space-y-2 text-xs">
                  {#each selectedRelationships as row}
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-2"
                    >
                      <p class="text-muted-foreground">{row.label}</p>
                      <p class="font-medium text-foreground">
                        {row.value ?? "Unavailable"}
                      </p>
                      <p class="mt-1 text-muted-foreground">
                        {row.explanation}
                      </p>
                    </div>
                  {/each}
                </div>
              {/if}

              {#if cockpitTab === "timeline"}
                <div class="space-y-2 text-xs">
                  {#if selectedTimeline.length > 0}
                    {#each selectedTimeline as event}
                      <div
                        class="rounded-lg border border-border/60 bg-background/60 p-2"
                      >
                        <p class="font-medium text-foreground">{event.title}</p>
                        <p class="text-muted-foreground">
                          {new Date(event.happened_at).toLocaleString()} • {event.origin}
                        </p>
                        <p class="mt-1 text-muted-foreground">
                          {event.summary}
                        </p>
                        <p class="mt-1 text-muted-foreground">
                          This event explains how the asset reached its current
                          operational state.
                        </p>
                      </div>
                    {/each}
                  {:else}
                    <p class="text-muted-foreground">
                      Timeline is unavailable because no lifecycle events are
                      currently linked for this asset.
                    </p>
                  {/if}
                </div>
              {/if}

              {#if cockpitTab === "actions"}
                <div class="space-y-3 text-xs">
                  {#if selectedPrimaryAction}
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-3"
                    >
                      <div class="flex items-start justify-between gap-2">
                        <div>
                          <p
                            class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                          >
                            {actionPresentationLabel(selectedPrimaryAction)}
                          </p>
                          <p class="mt-1 text-sm font-semibold text-foreground">
                            {selectedPrimaryAction.label}
                          </p>
                        </div>
                        <span
                          class={`rounded-full border px-2 py-0.5 ${actionPresentationClass(selectedPrimaryAction)}`}
                          >{workflowOutcomeLabel(selectedAsset)}</span
                        >
                      </div>
                      {#if selectedAsset.action_manifest.primary_action_reasoning.length > 0}
                        <div class="mt-3 space-y-2 text-muted-foreground">
                          {#each selectedAsset.action_manifest.primary_action_reasoning as detail}
                            <p>{detail}</p>
                          {/each}
                        </div>
                      {/if}
                      <div class="mt-3 flex items-center justify-between gap-2">
                        <p class="text-muted-foreground">
                          {selectedPrimaryAction.description ||
                            "No description"}
                        </p>
                        <button
                          type="button"
                          class={`rounded-full border px-3 py-1 ${selectedPrimaryAction.presentation === "required" ? "border-destructive/60 text-destructive" : "border-primary text-primary"}`}
                          onclick={() =>
                            runManifestAction(selectedPrimaryAction)}
                          disabled={inspectorActionBusy}
                          >{inspectorActionBusy
                            ? "Running..."
                            : selectedPrimaryAction.label}</button
                        >
                      </div>
                    </div>
                  {/if}

                  {#if selectedRequiredActions.length > 0}
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-2"
                    >
                      <p
                        class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                      >
                        Required Actions
                      </p>
                      <div class="mt-2 space-y-2">
                        {#each selectedRequiredActions as action}
                          <div
                            class="rounded-md border border-destructive/30 bg-background/70 p-2"
                          >
                            <div class="flex items-start justify-between gap-2">
                              <div>
                                <p class="font-medium text-foreground">
                                  {action.label}
                                </p>
                                <p class="text-muted-foreground">
                                  {action.description || "No description"}
                                </p>
                              </div>
                              <span
                                class="rounded-full border border-destructive/60 px-2 py-0.5 text-destructive"
                              >
                                Required
                              </span>
                            </div>
                          </div>
                        {/each}
                      </div>
                    </div>
                  {/if}

                  {#if selectedRecommendedActions.length > 0}
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-2"
                    >
                      <p
                        class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                      >
                        Recommended Actions
                      </p>
                      <div class="mt-2 space-y-2">
                        {#each selectedRecommendedActions as action}
                          <div
                            class="rounded-md border border-border/50 bg-background/70 p-2"
                          >
                            <div class="flex items-start justify-between gap-2">
                              <div>
                                <p class="font-medium text-foreground">
                                  {action.label}
                                </p>
                                <p class="text-muted-foreground">
                                  {action.description || "No description"}
                                </p>
                              </div>
                              <span
                                class="rounded-full border border-emerald-500/60 px-2 py-0.5 text-emerald-200"
                              >
                                Recommended
                              </span>
                            </div>
                            <div
                              class="mt-2 rounded-md border border-border/40 bg-background/60 p-2 text-muted-foreground"
                            >
                              <p class="font-medium text-foreground">
                                Safety, Outcome, and Reversibility
                              </p>
                              {#if action.impact_preview.length > 0}
                                <ul class="mt-1 space-y-1">
                                  {#each action.impact_preview as detail}
                                    <li>{detail}</li>
                                  {/each}
                                </ul>
                              {:else}
                                <p class="mt-1">
                                  Supporting recommendation details are
                                  unavailable.
                                </p>
                              {/if}
                            </div>
                            <div class="mt-2 flex justify-end">
                              <button
                                type="button"
                                class="rounded-full border border-primary px-2 py-1 text-primary"
                                onclick={() => runManifestAction(action)}
                                disabled={inspectorActionBusy}
                                >{inspectorActionBusy
                                  ? "Running..."
                                  : action.label}</button
                              >
                            </div>
                          </div>
                        {/each}
                      </div>
                    </div>
                  {/if}

                  {#if groupedSecondaryActions.length > 0}
                    {#each groupedSecondaryActions as group}
                      <div
                        class="rounded-lg border border-border/60 bg-background/60 p-2"
                      >
                        <p
                          class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                        >
                          Additional {group.category}
                        </p>
                        <div class="mt-2 space-y-2">
                          {#each group.actions as action}
                            <div
                              class="rounded-md border border-border/50 bg-background/70 p-2"
                            >
                              <div
                                class="flex items-start justify-between gap-2"
                              >
                                <div>
                                  <p class="font-medium text-foreground">
                                    {action.label}
                                  </p>
                                  <p class="text-muted-foreground">
                                    {action.description || "No description"}
                                  </p>
                                </div>
                                <span
                                  class={`rounded-full border px-2 py-0.5 ${action.risk === "high" ? "border-destructive/60 text-destructive" : action.risk === "medium" ? "border-orange-400/60 text-orange-300" : "border-emerald-500/60 text-emerald-300"}`}
                                  >{actionPresentationLabel(action)}</span
                                >
                              </div>
                              <div
                                class="mt-2 flex items-center justify-between gap-2"
                              >
                                <p class="text-muted-foreground">
                                  {action.kind} • {action.automation}
                                </p>
                                <button
                                  type="button"
                                  class="rounded-full border border-border px-2 py-1"
                                  onclick={() => runManifestAction(action)}
                                  disabled={inspectorActionBusy}
                                  >{inspectorActionBusy
                                    ? "Running..."
                                    : "Run"}</button
                                >
                              </div>
                              <div
                                class="mt-2 rounded-md border border-border/40 bg-background/60 p-2 text-muted-foreground"
                              >
                                <p class="font-medium text-foreground">
                                  Impact Preview
                                </p>
                                {#if action.impact_preview.length > 0}
                                  <ul class="mt-1 space-y-1">
                                    {#each action.impact_preview as detail}
                                      <li>{detail}</li>
                                    {/each}
                                  </ul>
                                {:else}
                                  <p class="mt-1">
                                    Impact preview unavailable because no
                                    supporting evidence is currently linked.
                                  </p>
                                {/if}
                              </div>
                            </div>
                          {/each}
                        </div>
                      </div>
                    {/each}
                  {:else if !selectedPrimaryAction && selectedRequiredActions.length === 0 && selectedRecommendedActions.length === 0}
                    <p class="text-muted-foreground">No actions available.</p>
                  {/if}
                </div>
              {/if}

              {#if cockpitTab === "execution"}
                <div class="space-y-2 text-xs">
                  <div
                    class="rounded-lg border border-border/60 bg-background/60 p-2"
                  >
                    <p class="text-muted-foreground">Execution Preview</p>
                    <p class="font-medium text-foreground">
                      Expected Recovery {formatFileSize(
                        inspectorPreview?.preview?.estimated_recovery_bytes ??
                          0,
                      )}
                    </p>
                    {#if inspectorPreview?.preview?.details?.length}
                      <ul class="mt-2 space-y-1 text-muted-foreground">
                        {#each inspectorPreview.preview.details as detail}
                          <li>{detail}</li>
                        {/each}
                      </ul>
                    {/if}
                  </div>

                  <div
                    class="rounded-lg border border-border/60 bg-background/60 p-2"
                  >
                    <p class="text-muted-foreground">Validation</p>
                    {#if inspectorValidation?.validation?.checks?.length}
                      <div class="mt-2 space-y-1">
                        {#each inspectorValidation.validation.checks as check}
                          <p
                            class={check.passed
                              ? "text-emerald-300"
                              : "text-destructive"}
                          >
                            {check.passed ? "✓" : "✕"}
                            {check.label} • {check.detail}
                          </p>
                        {/each}
                      </div>
                    {:else}
                      <p class="text-muted-foreground">
                        Validation unavailable.
                      </p>
                    {/if}
                  </div>

                  {#if selectedExecutionItem}
                    <div
                      class="rounded-lg border border-border/60 bg-background/60 p-2"
                    >
                      <p class="text-muted-foreground">Execution Monitor</p>
                      <p class="font-medium text-foreground">
                        {selectedExecutionItem.message ||
                          selectedExecutionItem.status}
                      </p>
                      <div class="mt-2 space-y-1">
                        {#each selectedExecutionItem.stages as stage}
                          <p class="text-muted-foreground">
                            {stage.label}: {stage.status}
                          </p>
                        {/each}
                      </div>
                    </div>
                  {/if}
                </div>
              {/if}

              {#if cockpitTab === "history"}
                <div class="space-y-2 text-xs">
                  {#if selectedHistoryRows.length > 0}
                    {#each selectedHistoryRows as row}
                      <div
                        class="rounded-lg border border-border/60 bg-background/60 p-2"
                      >
                        <p class="font-medium text-foreground">{row.action}</p>
                        <p class="text-muted-foreground">
                          {row.status} • {new Date(
                            row.created_at,
                          ).toLocaleString()}
                        </p>
                        <p class="text-muted-foreground">
                          Recovered {formatFileSize(row.recovered_space_bytes)}
                        </p>
                      </div>
                    {/each}
                  {:else}
                    <p class="text-muted-foreground">
                      No history for this asset yet.
                    </p>
                  {/if}
                </div>
              {/if}

              {#if cockpitTab === "logs"}
                <div class="space-y-2 text-xs">
                  {#if selectedAuditRows.length > 0}
                    {#each selectedAuditRows.slice(0, 30) as row}
                      <div
                        class="rounded-lg border border-border/60 bg-background/60 p-2"
                      >
                        <p class="font-medium text-foreground">{row.action}</p>
                        <p class="text-muted-foreground">
                          {row.result} • {new Date(
                            row.created_at,
                          ).toLocaleString()}
                        </p>
                        <p class="text-muted-foreground">
                          {row.target_type}#{row.target_id ?? "n/a"} • {formatFileSize(
                            row.recovery_bytes,
                          )}
                        </p>
                      </div>
                    {/each}
                  {:else}
                    <p class="text-muted-foreground">
                      No diagnostic logs available for this asset.
                    </p>
                  {/if}
                </div>
              {/if}
            </div>
          {:else}
            <p class="mt-2 text-sm text-muted-foreground">
              Select an asset card to inspect why it happened, where files are,
              which apps own it, and what you can do next.
            </p>
          {/if}
        </aside>
      </section>

      {#if executionSession && isExecutionTerminal(executionSession) && executionSummary}
        <section
          class="rounded-2xl border border-border/70 bg-card/60 p-4"
          in:slide
        >
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 class="text-lg font-semibold text-foreground">
                Execution Summary
              </h2>
              <p class="text-sm text-muted-foreground">
                {executionSummary.successfulCount} successful • {executionSummary.warningCount}
                warnings • {executionSummary.failedCount} failed
              </p>
            </div>
            <div
              class="grid grid-cols-2 gap-2 text-sm text-muted-foreground md:grid-cols-4"
            >
              <div
                class="rounded-xl border border-border/60 bg-background/60 px-3 py-2"
              >
                <p>Successful</p>
                <p class="mt-1 text-lg font-semibold text-foreground">
                  {executionSummary.successfulCount}
                </p>
              </div>
              <div
                class="rounded-xl border border-border/60 bg-background/60 px-3 py-2"
              >
                <p>Warnings</p>
                <p class="mt-1 text-lg font-semibold text-foreground">
                  {executionSummary.warningCount}
                </p>
              </div>
              <div
                class="rounded-xl border border-border/60 bg-background/60 px-3 py-2"
              >
                <p>Failed</p>
                <p class="mt-1 text-lg font-semibold text-foreground">
                  {executionSummary.failedCount}
                </p>
              </div>
              <div
                class="rounded-xl border border-border/60 bg-background/60 px-3 py-2"
              >
                <p>Recovered Space</p>
                <p class="mt-1 text-lg font-semibold text-foreground">
                  {formatFileSize(executionSummary.recoveredSpace)}
                </p>
                <p class="text-xs">
                  {formatDuration(executionSummary.elapsedMs)}
                </p>
              </div>
            </div>
          </div>

          <div class="mt-4 grid gap-3 lg:grid-cols-3">
            <details
              class="rounded-xl border border-border/60 bg-background/50 p-3"
            >
              <summary class="cursor-pointer font-medium text-foreground"
                >Successful ({executionSummary.successfulCount})</summary
              >
              <div class="mt-3 space-y-2 text-sm text-muted-foreground">
                {#each executionSummary.successful as item}
                  <div
                    class="rounded-lg border border-border/50 bg-background/70 px-3 py-2"
                  >
                    <p class="font-medium text-foreground">
                      {item.title || item.recommendation_id}
                    </p>
                    <p>{item.message || "Completed"}</p>
                  </div>
                {/each}
              </div>
            </details>

            <details
              class="rounded-xl border border-border/60 bg-background/50 p-3"
            >
              <summary class="cursor-pointer font-medium text-foreground"
                >Warnings ({executionSummary.warningCount})</summary
              >
              <div class="mt-3 space-y-2 text-sm text-muted-foreground">
                {#each executionSummary.warnings as item}
                  <div
                    class="rounded-lg border border-border/50 bg-background/70 px-3 py-2"
                  >
                    <p class="font-medium text-foreground">
                      {item.title || item.recommendation_id}
                    </p>
                    <p>{item.message || "Blocked"}</p>
                  </div>
                {/each}
              </div>
            </details>

            <details
              class="rounded-xl border border-border/60 bg-background/50 p-3"
            >
              <summary class="cursor-pointer font-medium text-foreground"
                >Failures ({executionSummary.failedCount})</summary
              >
              <div class="mt-3 space-y-2 text-sm text-muted-foreground">
                {#each executionSummary.failed as item}
                  <div
                    class="rounded-lg border border-border/50 bg-background/70 px-3 py-2"
                  >
                    <p class="font-medium text-foreground">
                      {item.title || item.recommendation_id}
                    </p>
                    <p>{item.message || "Failed"}</p>
                  </div>
                {/each}
              </div>
            </details>
          </div>
        </section>
      {/if}

      <section class="grid gap-4 xl:grid-cols-2">
        <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
          <h2 class="text-lg font-semibold text-foreground">
            Execution History
          </h2>
          {#if executionHistory && executionHistory.items.length > 0}
            <div class="mt-3 space-y-2 text-sm">
              {#each executionHistory.items.slice(0, 8) as row}
                <details
                  class="rounded-xl border border-border/50 bg-background/70 px-3 py-3"
                >
                  <summary class="cursor-pointer list-none">
                    <div
                      class="flex flex-wrap items-center justify-between gap-2"
                    >
                      <div>
                        <p class="font-medium text-foreground">
                          {row.action === "bulk_execute"
                            ? "Operations Execution"
                            : row.action}
                        </p>
                        <p class="text-xs text-muted-foreground">
                          {row.selected_count} assets • {row.status} • {formatDuration(
                            row.elapsed_ms,
                          )}
                        </p>
                      </div>
                      <div class="text-xs text-muted-foreground">
                        <p>{row.successful} successful • {row.failed} failed</p>
                        <p>{formatFileSize(row.recovered_space_bytes)}</p>
                      </div>
                    </div>
                  </summary>
                  <div class="mt-3 space-y-2 text-xs text-muted-foreground">
                    {#each row.items as item}
                      <div
                        class="rounded-lg border border-border/40 bg-background/60 px-3 py-2"
                      >
                        <div class="flex items-center justify-between gap-2">
                          <span class="font-medium text-foreground"
                            >{item.title}</span
                          >
                          <span>{item.status}</span>
                        </div>
                        <p class="mt-1">{item.message}</p>
                      </div>
                    {/each}
                  </div>
                </details>
              {/each}
            </div>
          {:else}
            <p class="mt-2 text-sm text-muted-foreground">
              No execution history yet.
            </p>
          {/if}
        </div>

        <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
          <h2 class="text-lg font-semibold text-foreground">Audit Log</h2>
          {#if auditTrail && auditTrail.items.length > 0}
            <div class="mt-3 space-y-2 text-xs">
              {#each auditTrail.items.slice(0, 10) as row}
                <div
                  class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/50 bg-background/70 px-3 py-2"
                >
                  <span class="text-foreground"
                    >{row.action} • {row.target_type}#{row.target_id ??
                      "n/a"}</span
                  >
                  <span class="text-muted-foreground"
                    >{row.result} • {formatFileSize(row.recovery_bytes)}</span
                  >
                </div>
              {/each}
            </div>
          {:else}
            <p class="mt-2 text-sm text-muted-foreground">
              No operation history yet.
            </p>
          {/if}
        </div>
      </section>
    {/if}
  </div>
</div>
