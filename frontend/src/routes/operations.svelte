<script lang="ts">
  import { flip } from "svelte/animate";
  import { onDestroy, onMount } from "svelte";
  import { fade, slide } from "svelte/transition";
  import { get_api, post_api } from "$lib/api";
  import WorkspaceToolbar from "$lib/components/workspace/workspace-toolbar.svelte";
  import type {
    MediaFilterCatalogResponse,
    MediaFilterOptionResponse,
    MieOperationsResponse,
    OperationActionManifestAction,
    OperationAuditListResponse,
    OperationExecutionHistoryListResponse,
    OperationExecutionItemProgress,
    OperationExecutionSessionResponse,
    OperationWorkflowResponse,
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
    inferCategory,
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
    | "locations"
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
    visibleAssetLimit: number;
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
    { key: "locations", label: "Locations" },
    { key: "applications", label: "Applications" },
    { key: "relationships", label: "Relationships" },
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
  let executionHistory = $state<OperationExecutionHistoryListResponse | null>(null);
  let filterCatalog = $state<MediaFilterCatalogResponse | null>(null);

  let search = $state("");
  let sortBy = $state<SortBy>("recovery");
  let sortOrder = $state<"asc" | "desc">("desc");
  let candidatesOnly = $state(false);
  let arrFilterIds = $state<number[]>([]);
  let decisionFilterIds = $state<number[]>([]);
  let smartFilterIds = $state<number[]>([]);
  let visibleAssetLimit = $state(50);
  let posterSize = $state(170);
  let displayMode = $state<ViewMode>("grid");

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
    return (workspace?.workflow?.stages ?? []).flatMap((stage) => stage.assets ?? []);
  });

  const activeStage = $derived.by(() => {
    return stageRows.find((row) => row.key === selectedStage) ?? stageRows[0] ?? null;
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

  const displayedAssets = $derived.by(() => {
    return filteredAssets.slice(0, Math.max(1, visibleAssetLimit));
  });

  const orderedFilteredIds = $derived.by(() => filteredAssets.map((asset) => asset.id));
  const displayedIds = $derived.by(() => displayedAssets.map((asset) => asset.id));

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
    return Object.values(stageSelections).reduce((count, ids) => count + ids.size, 0);
  });

  const displayedSelectedCount = $derived.by(() => {
    return displayedAssets.filter((asset) => selectedIdsInStage.has(asset.id)).length;
  });

  const allDisplayedSelected = $derived.by(() => {
    return displayedAssets.length > 0 && displayedSelectedCount === displayedAssets.length;
  });

  const someDisplayedSelected = $derived.by(() => {
    return displayedSelectedCount > 0 && displayedSelectedCount < displayedAssets.length;
  });

  const selectableRecommendationIds = $derived.by(() => {
    return new Set((workspace?.recommendations.items ?? []).map((row) => row.id));
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
    return allWorkflowAssets.find((asset) => asset.id === selectedAssetId) ?? null;
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
    return Math.round((workflowProgress.completed / workflowProgress.total) * 100);
  });

  const executionActive = $derived.by(() => {
    return !!executionSession && ["queued", "running"].includes(executionSession.status);
  });

  const executionProgressPercent = $derived.by(() => {
    if (!executionSession?.total) return 0;
    return Math.round((executionSession.completed / executionSession.total) * 100);
  });

  const executionSummary = $derived.by(() => {
    return executionSession ? summarizeExecutionSession(executionSession) : null;
  });

  const executionItemsByRecommendation = $derived.by(() => {
    return new Map(
      (executionSession?.items ?? []).map((item) => [item.recommendation_id, item]),
    );
  });

  const selectedExecutionItem = $derived.by(() => {
    if (!selectedAssetId) return null;
    return executionItemsByRecommendation.get(selectedAssetId) ?? null;
  });

  const selectedRecommendation = $derived.by(() => {
    if (!selectedAssetId) return null;
    return (
      workspace?.recommendations.items.find((item) => item.id === selectedAssetId) ?? null
    );
  });

  const selectedManifestActions = $derived.by(() => {
    return (
      selectedRecommendation?.action_manifest?.available_actions ??
      selectedAsset?.action_manifest?.available_actions ??
      []
    ) as OperationActionManifestAction[];
  });

  const groupedManifestActions = $derived.by(() => {
    const groups = new Map<string, OperationActionManifestAction[]>();
    for (const row of selectedManifestActions) {
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
    const targetId = selectedAsset.target_id ? Number(selectedAsset.target_id) : null;
    return (workspace?.timeline_summary?.highlights ?? []).filter((event) => {
      if (event.media_type && mediaType && event.media_type !== mediaType) return false;
      if (event.media_id !== null && targetId !== null && event.media_id !== targetId) return false;
      return event.title.toLowerCase().includes(selectedAsset.title.toLowerCase()) ||
        event.media_id === targetId;
    });
  });

  const selectedHistoryRows = $derived.by(() => {
    if (!selectedAsset) return [];
    const targetId = selectedAsset.target_id;
    return (executionHistory?.items ?? []).filter((row) =>
      row.items.some((item) => item.recommendation_id === selectedAsset.id || item.target_id === targetId),
    );
  });

  const selectedAuditRows = $derived.by(() => {
    if (!selectedAsset) return [];
    return (auditTrail?.items ?? []).filter((row) => {
      if (selectedAsset.target_id && row.target_id === selectedAsset.target_id) return true;
      return row.target_type === selectedAsset.target_type;
    });
  });

  const selectedLocations = $derived.by(() => {
    if (!selectedAsset) return [];
    return [
      { key: "downloads", label: "Downloads", path: selectedAsset.download_location },
      { key: "library", label: "Library", path: selectedAsset.library_location },
      { key: "temporary", label: "Temporary", path: "/app/transcode/" },
      { key: "cache", label: "Cache", path: "/metadata/" },
    ];
  });

  function normalizeActionId(action: string) {
    const source = String(action || "").trim().toLowerCase();
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
      inspectorActionMessage = e?.message ?? "Failed to load inspector tab data";
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
        window.open(`${window.location.origin}/${target}`, "_blank", "noopener,noreferrer");
        inspectorActionMessage = `${action.label} launched.`;
        return;
      }

      if (action.id === "ignore_recommendation" || action.id === "manual_review") {
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
      inspectorActionMessage = result.execution.message || `${action.label} completed.`;
      await Promise.all([loadWorkspace(), loadHistory()]);
    } catch (e: any) {
      inspectorActionMessage = e?.message ?? `Failed to execute ${action.label}`;
    } finally {
      inspectorActionBusy = false;
    }
  }

  function addArrayParams(params: URLSearchParams, key: string, values: number[]) {
    for (const value of values) {
      params.append(key, String(value));
    }
  }

  function isExecutionTerminal(session: OperationExecutionSessionResponse | null): boolean {
    return !!session && ["completed", "failed", "partial"].includes(session.status);
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
        if (!nextSelections[stageKey]) nextSelections[stageKey] = new Set<string>();
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
      arrFilterIds = Array.isArray(prefs.arrFilterIds) ? prefs.arrFilterIds : arrFilterIds;
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
      visibleAssetLimit = prefs.visibleAssetLimit ?? visibleAssetLimit;
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
      visibleAssetLimit,
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

  async function loadWorkspace() {
    const params = new URLSearchParams();
    params.set("candidates_only", String(candidatesOnly));
    addArrayParams(params, "arr_filter_ids", arrFilterIds);
    addArrayParams(params, "decision_filter_ids", decisionFilterIds);
    addArrayParams(params, "smart_filter_ids", smartFilterIds);
    const response = await get_api<MieOperationsResponse>(`/api/mie/operations?${params.toString()}`);
    workspace = response;
    reconcileSelections(response);
  }

  async function loadHistory() {
    auditTrail = await get_api<OperationAuditListResponse>("/api/operations/audit");
    executionHistory = await get_api<OperationExecutionHistoryListResponse>(
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
        workflowProgress = { ...workflowProgress, failed: workflowProgress.failed + 1 };
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

  function executionStageClass(status: string) {
    if (status === "completed") return "border-emerald-500/40 bg-emerald-500/10 text-emerald-200";
    if (status === "running") return "border-primary/50 bg-primary/10 text-primary";
    if (status === "failed") return "border-destructive/40 bg-destructive/10 text-destructive";
    if (status === "skipped") return "border-border/60 bg-secondary/30 text-muted-foreground";
    return "border-border/60 bg-background/60 text-muted-foreground";
  }

  function itemExecution(assetId: string): OperationExecutionItemProgress | null {
    return executionItemsByRecommendation.get(assetId) ?? null;
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
    if (selectedFilter && !stageFilterRows.some((row) => row.key === selectedFilter)) {
      selectedFilter = null;
    }
  });

  $effect(() => {
    if (!selectedAssetId) return;
    void ensureCockpitTabData(cockpitTab);
  });

  onMount(async () => {
    loadPrefs();
    applyHashSelection();
    await load();
  });

  onDestroy(() => {
    stopExecutionPolling();
  });
</script>

<svelte:window onkeydown={onKeyboardShortcuts} />

<div class="p-2.5 md:p-8">
  <div class="mx-auto max-w-[1520px] space-y-6">
    <header class="rounded-[2rem] border border-border/70 bg-gradient-to-br from-card via-background to-secondary/20 p-6 shadow-xl shadow-black/10">
      <p class="text-xs uppercase tracking-[0.3em] text-muted-foreground">
        Operations Workspace
      </p>
      <h1 class="text-4xl font-black tracking-tight text-foreground">
        Media Lifecycle Console
      </h1>
      <p class="mt-2 max-w-3xl text-sm text-muted-foreground">
        Execute lifecycle work without losing context. Preview, validate, and run bulk actions while the workspace stays live.
      </p>
    </header>

    {#if loading}
      <div class="rounded-xl border border-border bg-card p-6 text-muted-foreground">
        Loading operations workspace...
      </div>
    {:else if error}
      <div class="rounded-xl border border-destructive/40 bg-destructive/10 p-6 text-destructive">
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
        perPage={visibleAssetLimit}
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
        onPerPageChange={(value) => (visibleAssetLimit = value)}
        onPosterSizeChange={(value) => (posterSize = value)}
        onViewModeChange={(value) => (displayMode = value as ViewMode)}
        onBulkAction={handleToolbarBulkAction}
      />

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
              <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">{stage.title}</p>
              <p class="mt-2 text-2xl font-black text-foreground">{stage.count}</p>
              <p class="mt-1 text-xs text-muted-foreground">{stage.description}</p>
              <div class="mt-3 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
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
              {option === "all" ? "All Media" : option[0].toUpperCase() + option.slice(1)}
            </button>
          {/each}
        </div>

        <div class="flex flex-wrap gap-2">
          {#each [
            ["all", "All"],
            ["ready", "Ready"],
            ["blocked", "Blocked"],
            ["needs_review", "Needs Review"],
            ["high_confidence", "High Confidence"],
            ["low_confidence", "Low Confidence"],
          ] as [key, label]}
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

      <section class="sticky top-2 z-20 rounded-2xl border border-border/70 bg-background/95 p-3 shadow backdrop-blur">
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="font-semibold text-foreground">Selected:</span>
          <span class="rounded-full border border-border px-2 py-1 text-xs text-foreground">{selectedAssets.length} Visible</span>
          <span class="rounded-full border border-border px-2 py-1 text-xs text-muted-foreground">Recommendation-backed: {selectedRecommendationIds.length}</span>
          <span class="rounded-full border border-border px-2 py-1 text-xs text-muted-foreground">Lane: {activeStage?.title ?? "Workflow"}</span>

          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40" onclick={selectAllFiltered}>Select All</button>
          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40" onclick={clearSelection}>Clear Selection</button>
          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40" onclick={() => bulkAction("preview")} disabled={workflowBusy || executionActive}>Preview</button>
          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40" onclick={() => bulkAction("validate")} disabled={workflowBusy || executionActive}>Validate</button>
          <button type="button" class="rounded-full border border-primary bg-primary/10 px-3 py-1.5 text-xs text-primary hover:bg-primary/20" onclick={beginExecution} disabled={workflowBusy || executionActive}>Execute</button>
        </div>

        {#if workflowBusy || workflowResults.length > 0 || workflowError || executionSession || executionError}
          <div class="mt-3 rounded-xl border border-border/60 bg-card/60 p-3 text-xs" transition:slide>
            {#if workflowResults.length > 0}
              <div class="flex flex-wrap items-center gap-2 text-muted-foreground">
                <span>Assets Selected {selectedRecommendationIds.length}</span>
                <span>Validated {bulkSummary.validated}</span>
                <span>Blocked {bulkSummary.blocked}</span>
                <span>Warnings {bulkSummary.warnings}</span>
                <span>Expected Success {bulkSummary.expectedSuccess}</span>
                <span>Estimated Recovery {formatFileSize(bulkSummary.estimatedRecovery)}</span>
              </div>
            {/if}

            {#if workflowBusy}
              <div class="mt-3 space-y-1">
                <p class="text-muted-foreground">{workflowMode === "preview" ? "Building preview..." : "Running validation..."}</p>
                <div class="h-2 w-full overflow-hidden rounded-full bg-secondary/50">
                  <div class="h-full bg-primary transition-all" style={`width:${workflowProgressPercent}%`}></div>
                </div>
                <p class="text-muted-foreground">
                  Completed {workflowProgress.completed} • Remaining {Math.max(0, workflowProgress.total - workflowProgress.completed)} • Failed {workflowProgress.failed}
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
                            : executionSession.current_step_label || "Executing..."}
                    </p>
                    <p class="text-muted-foreground">
                      {executionSession.current_asset_title || "Workspace remains live while operations continue."}
                    </p>
                  </div>
                  <div class="flex flex-wrap gap-2 text-muted-foreground">
                    <span>{executionSession.completed} / {executionSession.total} Assets</span>
                    <span>Elapsed {formatDuration(executionSession.elapsed_ms)}</span>
                    {#if executionSession.estimated_remaining_ms !== null}
                      <span>ETA {formatDuration(executionSession.estimated_remaining_ms)}</span>
                    {/if}
                  </div>
                </div>

                <div class="h-2 w-full overflow-hidden rounded-full bg-secondary/50">
                  <div class="h-full bg-primary transition-all duration-300" style={`width:${executionProgressPercent}%`}></div>
                </div>

                <p class="text-muted-foreground">
                  Completed {executionSession.completed} • Remaining {executionSession.remaining} • Failed {executionSession.failed} • Warnings {executionSession.warnings}
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
            <h2 class="text-lg font-semibold text-foreground">Assets in {activeStage?.title ?? "Stage"}</h2>
            <p class="text-xs text-muted-foreground">
              Showing {displayedAssets.length} of {filteredAssets.length} assets in {stageTitle(activeStage?.key)}
            </p>
          </div>

          {#if filteredAssets.length === 0}
            <p class="rounded-2xl border border-border/70 bg-card/60 p-4 text-sm text-muted-foreground">
              No assets for this stage/filter combination.
            </p>
          {:else}
            <div class={displayMode === "list" ? "space-y-3" : "grid gap-3 md:grid-cols-2 2xl:grid-cols-3"}>
              {#each displayedAssets as asset, index (`${asset.id}:${asset.current_stage ?? ""}:${index}`)}
                {@const hasPoster = !!asset.poster_url}
                {@const executionItem = itemExecution(asset.id)}
                <article
                  animate:flip={{ duration: 220 }}
                  class={`rounded-2xl border bg-card/60 p-3 transition ${selectedAssetId === asset.id ? "border-primary shadow-lg shadow-primary/10" : "border-border/70 hover:bg-card"}`}
                >
                  <div class="mb-2 flex items-start justify-between gap-2">
                    <label class="inline-flex items-center gap-2 text-xs text-muted-foreground">
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
                    class={displayMode === "list" ? "grid w-full gap-3 text-left md:grid-cols-[140px_minmax(0,1fr)]" : "w-full text-left"}
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
                        <p class="text-sm font-semibold text-foreground">Missing Artwork</p>
                        <p class="mt-1 text-xs text-muted-foreground">Artwork Repair Available</p>
                      </div>
                    {/if}

                    <div class="mt-3 space-y-2 md:mt-0">
                      <div class="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <h3 class="line-clamp-2 text-base font-semibold text-foreground">{asset.title}</h3>
                          <p class="text-xs text-muted-foreground">
                            {asset.year ?? "Year n/a"} • {asset.media_type ?? inferCategory(asset)} • {asset.current_stage}
                          </p>
                        </div>
                        <div class="flex flex-wrap items-center gap-2 text-xs">
                          <span class="rounded-full border border-border px-2 py-0.5 text-muted-foreground">Risk {riskLabel(asset.risk_level)}</span>
                          {#if asset.estimated_space_recovery > 0}
                            <span class="rounded-full border border-border px-2 py-0.5 text-muted-foreground">Recoverable {formatFileSize(asset.estimated_space_recovery)}</span>
                          {/if}
                        </div>
                      </div>

                      <div class="rounded-lg bg-background/70 p-2">
                        <p class="text-xs uppercase tracking-[0.14em] text-muted-foreground">Current Status</p>
                        <p class="mt-1 text-sm text-foreground">{asset.current_status}</p>
                      </div>

                      <div class="rounded-lg bg-background/70 p-2">
                        <p class="text-xs uppercase tracking-[0.14em] text-muted-foreground">Recommendation</p>
                        <p class="mt-1 text-sm font-semibold text-foreground">{asset.next_action.replaceAll("_", " ")}</p>
                        <p class="mt-1 text-xs text-muted-foreground">{asset.recommendation}</p>
                      </div>

                      <div>
                        <div class="flex items-center justify-between text-xs">
                          <span class="text-muted-foreground">Confidence</span>
                          <span class="text-foreground">{confidenceLabel(asset.confidence)} {asset.confidence ?? 0}%</span>
                        </div>
                        <div class="mt-1 h-2 overflow-hidden rounded-full bg-secondary/50">
                          <div class={`h-full ${confidenceBarClass(asset.confidence)}`} style={`width:${asset.confidence ?? 0}%`}></div>
                        </div>
                      </div>

                      {#if executionItem}
                        <div class="rounded-lg border border-border/60 bg-background/40 p-2">
                          <p class="text-xs uppercase tracking-[0.14em] text-muted-foreground">Execution Pipeline</p>
                          <div class="mt-2 flex flex-wrap gap-1.5">
                            {#each executionItem.stages as stage}
                              <span class={`rounded-full border px-2 py-1 text-[11px] ${executionStageClass(stage.status)}`}>
                                {stage.status === "completed" ? "✓" : stage.status === "running" ? "Running" : stage.status === "failed" ? "Failed" : stage.status === "skipped" ? "Skipped" : "Waiting"}
                                {stage.label}
                              </span>
                            {/each}
                          </div>
                        </div>
                      {/if}

                      <details class="rounded-lg border border-border/60 bg-background/40 p-2 text-xs text-muted-foreground">
                        <summary class="cursor-pointer font-medium text-foreground">Why?</summary>
                        <ul class="mt-2 space-y-1">
                          <li>✓ {asset.reason}</li>
                          {#if asset.library_location}<li>✓ Library path verified</li>{/if}
                          {#if asset.torrent_state}<li>✓ Torrent state {asset.torrent_state}</li>{/if}
                          {#if asset.import_state}<li>✓ Import state {asset.import_state}</li>{/if}
                          {#if asset.retention_policy}<li>✓ Retention policy {asset.retention_policy}</li>{/if}
                        </ul>
                      </details>

                      <details class="rounded-lg border border-border/60 bg-background/40 p-2 text-xs text-muted-foreground">
                        <summary class="cursor-pointer font-medium text-foreground">Technical Details</summary>
                        <div class="mt-2 space-y-1">
                          {#if asset.download_location}<p>Download: {asset.download_location}</p>{/if}
                          {#if asset.library_location}<p>Library: {asset.library_location}</p>{/if}
                          {#if asset.policy_name}<p>Policy: {asset.policy_name}</p>{/if}
                          {#if asset.graph_references.length > 0}
                            <p>Graph refs: {asset.graph_references.join(" • ")}</p>
                          {:else}
                            <p>Additional provider information unavailable.</p>
                          {/if}
                        </div>
                      </details>
                    </div>
                  </button>
                </article>
              {/each}
            </div>
          {/if}
        </div>

        <aside class="rounded-2xl border border-border/70 bg-card/60 p-4">
          <h2 class="text-lg font-semibold text-foreground">Operational Cockpit</h2>
          {#if selectedAsset}
            <div class="mt-3 space-y-3 text-sm" in:fade>
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
                <p class="rounded-lg border border-border/60 bg-background/60 px-3 py-2 text-xs text-muted-foreground">
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
                    <div class="flex h-72 w-full items-center justify-center rounded-xl border border-dashed border-border bg-secondary/20 text-xs text-muted-foreground">
                      Artwork unavailable
                    </div>
                  {/if}
                  <div class="grid grid-cols-2 gap-2 text-xs">
                    <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Title</p><p class="font-medium text-foreground">{selectedAsset.title}</p></div>
                    <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Year</p><p class="font-medium text-foreground">{selectedAsset.year ?? "Unknown"}</p></div>
                    <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Media Type</p><p class="font-medium text-foreground">{selectedAsset.media_type ?? "Unknown"}</p></div>
                    <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Lifecycle</p><p class="font-medium text-foreground">{selectedAsset.current_stage}</p></div>
                    <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Recommendation</p><p class="font-medium text-foreground">{selectedAsset.next_action.replaceAll("_", " ")}</p></div>
                    <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Confidence</p><p class="font-medium text-foreground">{selectedAsset.confidence ?? 0}%</p></div>
                    <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Health Status</p><p class="font-medium text-foreground">{selectedAsset.current_status}</p></div>
                    <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Current Owner</p><p class="font-medium text-foreground">{selectedAsset.policy_name ?? "Unavailable"}</p></div>
                  </div>
                </div>
              {/if}

              {#if cockpitTab === "status"}
                <div class="space-y-2 text-xs">
                  {#each [
                    ["Download", selectedAsset.torrent_state || "Unavailable"],
                    ["Import", selectedAsset.import_state || "Unavailable"],
                    ["Filesystem", selectedAsset.library_location ? "Healthy" : "Pending"],
                    ["Identity", selectedAsset.graph_references.length > 0 ? "Healthy" : "Unavailable"],
                    ["Metadata", selectedRecommendation ? "Pending" : "Unavailable"],
                    ["Artwork", selectedAsset.poster_url ? "Healthy" : "Warning"],
                    ["Collections", selectedAsset.policy_name ? "Pending" : "Unavailable"],
                    ["Retention", selectedAsset.retention_policy || "Unavailable"],
                    ["Cleanup", selectedAsset.current_stage === "cleanup" ? "Running" : "Pending"],
                  ] as [label, value]}
                    <div class="flex items-center justify-between rounded-lg border border-border/60 bg-background/60 px-3 py-2">
                      <span class="text-muted-foreground">{label}</span>
                      <span class="font-medium text-foreground">{value}</span>
                    </div>
                  {/each}
                </div>
              {/if}

              {#if cockpitTab === "locations"}
                <div class="space-y-2 text-xs">
                  {#each selectedLocations as row}
                    <div class="rounded-lg border border-border/60 bg-background/60 p-2">
                      <div class="flex items-center justify-between gap-2">
                        <p class="font-medium text-foreground">{row.label}</p>
                        <span class="text-muted-foreground">{row.path ? "Exists" : "Unavailable"}</span>
                      </div>
                      <p class="mt-1 break-all text-muted-foreground">{row.path ?? "Unknown"}</p>
                      <div class="mt-2 flex flex-wrap gap-1">
                        <button type="button" class="rounded-full border border-border px-2 py-1" onclick={() => openFilesystemPath(row.path)}>Open Folder</button>
                        <button type="button" class="rounded-full border border-border px-2 py-1" onclick={() => openFilesystemPath(row.path)}>Browse</button>
                        <button type="button" class="rounded-full border border-border px-2 py-1" onclick={() => copyPath(row.path)}>Copy Path</button>
                        <button type="button" class="rounded-full border border-border px-2 py-1" onclick={() => openFilesystemPath(row.path)}>Reveal File</button>
                      </div>
                    </div>
                  {/each}
                  <button type="button" class="w-full rounded-lg border border-border/60 bg-background/60 px-3 py-2 text-left" onclick={() => copyPath(`${selectedAsset.download_location ?? "n/a"} <> ${selectedAsset.library_location ?? "n/a"}`)}>Compare Locations</button>
                </div>
              {/if}

              {#if cockpitTab === "applications"}
                <div class="space-y-2 text-xs">
                  <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Requested By</p><p class="font-medium text-foreground">{selectedAsset.media_type === "movie" ? "Radarr" : selectedAsset.media_type === "series" ? "Sonarr" : "Unavailable"}</p></div>
                  <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Managed By</p><p class="font-medium text-foreground">Plex</p></div>
                  <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Download Client</p><p class="font-medium text-foreground">{selectedAsset.torrent_state ? "qBittorrent" : "Unavailable"}</p></div>
                  <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Indexer</p><p class="font-medium text-foreground">Unavailable</p></div>
                  <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Collection</p><p class="font-medium text-foreground">{selectedAsset.policy_name ?? "Unknown"}</p></div>
                  <div class="flex flex-wrap gap-1">
                    {#each selectedManifestActions.filter((row) => row.category === "external") as action}
                      <button type="button" class="rounded-full border border-border px-2 py-1" onclick={() => runManifestAction(action)} disabled={inspectorActionBusy}>{action.label}</button>
                    {/each}
                  </div>
                </div>
              {/if}

              {#if cockpitTab === "relationships"}
                <div class="space-y-2 text-xs">
                  <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">IMDb</p><p class="font-medium text-foreground">Unavailable</p></div>
                  <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">TMDB</p><p class="font-medium text-foreground">Unavailable</p></div>
                  <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">TVDB</p><p class="font-medium text-foreground">Unavailable</p></div>
                  <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Trakt</p><p class="font-medium text-foreground">Unavailable</p></div>
                  <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Plex GUID</p><p class="font-medium text-foreground">{selectedAsset.target_id ?? "Unavailable"}</p></div>
                  <div class="rounded-lg border border-border/60 bg-background/60 p-2"><p class="text-muted-foreground">Graph References</p><p class="font-medium text-foreground">{selectedAsset.graph_references.join(" • ") || "Unavailable"}</p></div>
                </div>
              {/if}

              {#if cockpitTab === "timeline"}
                <div class="space-y-2 text-xs">
                  {#if selectedTimeline.length > 0}
                    {#each selectedTimeline as event}
                      <div class="rounded-lg border border-border/60 bg-background/60 p-2">
                        <p class="font-medium text-foreground">{event.title}</p>
                        <p class="text-muted-foreground">{new Date(event.happened_at).toLocaleString()} • {event.origin}</p>
                        <p class="mt-1 text-muted-foreground">{event.summary}</p>
                      </div>
                    {/each}
                  {:else}
                    <p class="text-muted-foreground">No timeline events available for this asset.</p>
                  {/if}
                </div>
              {/if}

              {#if cockpitTab === "actions"}
                <div class="space-y-3 text-xs">
                  {#if groupedManifestActions.length > 0}
                    {#each groupedManifestActions as group}
                      <div class="rounded-lg border border-border/60 bg-background/60 p-2">
                        <p class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">{group.category}</p>
                        <div class="mt-2 space-y-2">
                          {#each group.actions as action}
                            <div class="rounded-md border border-border/50 bg-background/70 p-2">
                              <div class="flex items-start justify-between gap-2">
                                <div>
                                  <p class="font-medium text-foreground">{action.label}</p>
                                  <p class="text-muted-foreground">{action.description || "No description"}</p>
                                </div>
                                <span class={`rounded-full border px-2 py-0.5 ${action.risk === "high" ? "border-destructive/60 text-destructive" : action.risk === "medium" ? "border-orange-400/60 text-orange-300" : "border-emerald-500/60 text-emerald-300"}`}>Risk {action.risk}</span>
                              </div>
                              <div class="mt-2 flex items-center justify-between gap-2">
                                <p class="text-muted-foreground">{action.kind} • {action.automation}</p>
                                <button type="button" class="rounded-full border border-border px-2 py-1" onclick={() => runManifestAction(action)} disabled={inspectorActionBusy}>{inspectorActionBusy ? "Running..." : "Run"}</button>
                              </div>
                            </div>
                          {/each}
                        </div>
                      </div>
                    {/each}
                  {:else}
                    <p class="text-muted-foreground">No actions available.</p>
                  {/if}
                </div>
              {/if}

              {#if cockpitTab === "execution"}
                <div class="space-y-2 text-xs">
                  <div class="rounded-lg border border-border/60 bg-background/60 p-2">
                    <p class="text-muted-foreground">Execution Preview</p>
                    <p class="font-medium text-foreground">Expected Recovery {formatFileSize(inspectorPreview?.preview?.estimated_recovery_bytes ?? 0)}</p>
                    {#if inspectorPreview?.preview?.details?.length}
                      <ul class="mt-2 space-y-1 text-muted-foreground">
                        {#each inspectorPreview.preview.details as detail}
                          <li>{detail}</li>
                        {/each}
                      </ul>
                    {/if}
                  </div>

                  <div class="rounded-lg border border-border/60 bg-background/60 p-2">
                    <p class="text-muted-foreground">Validation</p>
                    {#if inspectorValidation?.validation?.checks?.length}
                      <div class="mt-2 space-y-1">
                        {#each inspectorValidation.validation.checks as check}
                          <p class={check.passed ? "text-emerald-300" : "text-destructive"}>{check.passed ? "✓" : "✕"} {check.label} • {check.detail}</p>
                        {/each}
                      </div>
                    {:else}
                      <p class="text-muted-foreground">Validation unavailable.</p>
                    {/if}
                  </div>

                  {#if selectedExecutionItem}
                    <div class="rounded-lg border border-border/60 bg-background/60 p-2">
                      <p class="text-muted-foreground">Execution Monitor</p>
                      <p class="font-medium text-foreground">{selectedExecutionItem.message || selectedExecutionItem.status}</p>
                      <div class="mt-2 space-y-1">
                        {#each selectedExecutionItem.stages as stage}
                          <p class="text-muted-foreground">{stage.label}: {stage.status}</p>
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
                      <div class="rounded-lg border border-border/60 bg-background/60 p-2">
                        <p class="font-medium text-foreground">{row.action}</p>
                        <p class="text-muted-foreground">{row.status} • {new Date(row.created_at).toLocaleString()}</p>
                        <p class="text-muted-foreground">Recovered {formatFileSize(row.recovered_space_bytes)}</p>
                      </div>
                    {/each}
                  {:else}
                    <p class="text-muted-foreground">No history for this asset yet.</p>
                  {/if}
                </div>
              {/if}

              {#if cockpitTab === "logs"}
                <div class="space-y-2 text-xs">
                  {#if selectedAuditRows.length > 0}
                    {#each selectedAuditRows.slice(0, 30) as row}
                      <div class="rounded-lg border border-border/60 bg-background/60 p-2">
                        <p class="font-medium text-foreground">{row.action}</p>
                        <p class="text-muted-foreground">{row.result} • {new Date(row.created_at).toLocaleString()}</p>
                        <p class="text-muted-foreground">{row.target_type}#{row.target_id ?? "n/a"} • {formatFileSize(row.recovery_bytes)}</p>
                      </div>
                    {/each}
                  {:else}
                    <p class="text-muted-foreground">No diagnostic logs available for this asset.</p>
                  {/if}
                </div>
              {/if}
            </div>
          {:else}
            <p class="mt-2 text-sm text-muted-foreground">
              Select an asset card to inspect why it happened, where files are, which apps own it, and what you can do next.
            </p>
          {/if}
        </aside>
      </section>

      {#if executionSession && isExecutionTerminal(executionSession) && executionSummary}
        <section class="rounded-2xl border border-border/70 bg-card/60 p-4" in:slide>
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 class="text-lg font-semibold text-foreground">Execution Summary</h2>
              <p class="text-sm text-muted-foreground">
                {executionSummary.successfulCount} successful • {executionSummary.warningCount} warnings • {executionSummary.failedCount} failed
              </p>
            </div>
            <div class="grid grid-cols-2 gap-2 text-sm text-muted-foreground md:grid-cols-4">
              <div class="rounded-xl border border-border/60 bg-background/60 px-3 py-2">
                <p>Successful</p>
                <p class="mt-1 text-lg font-semibold text-foreground">{executionSummary.successfulCount}</p>
              </div>
              <div class="rounded-xl border border-border/60 bg-background/60 px-3 py-2">
                <p>Warnings</p>
                <p class="mt-1 text-lg font-semibold text-foreground">{executionSummary.warningCount}</p>
              </div>
              <div class="rounded-xl border border-border/60 bg-background/60 px-3 py-2">
                <p>Failed</p>
                <p class="mt-1 text-lg font-semibold text-foreground">{executionSummary.failedCount}</p>
              </div>
              <div class="rounded-xl border border-border/60 bg-background/60 px-3 py-2">
                <p>Recovered Space</p>
                <p class="mt-1 text-lg font-semibold text-foreground">{formatFileSize(executionSummary.recoveredSpace)}</p>
                <p class="text-xs">{formatDuration(executionSummary.elapsedMs)}</p>
              </div>
            </div>
          </div>

          <div class="mt-4 grid gap-3 lg:grid-cols-3">
            <details class="rounded-xl border border-border/60 bg-background/50 p-3">
              <summary class="cursor-pointer font-medium text-foreground">Successful ({executionSummary.successfulCount})</summary>
              <div class="mt-3 space-y-2 text-sm text-muted-foreground">
                {#each executionSummary.successful as item}
                  <div class="rounded-lg border border-border/50 bg-background/70 px-3 py-2">
                    <p class="font-medium text-foreground">{item.title || item.recommendation_id}</p>
                    <p>{item.message || "Completed"}</p>
                  </div>
                {/each}
              </div>
            </details>

            <details class="rounded-xl border border-border/60 bg-background/50 p-3">
              <summary class="cursor-pointer font-medium text-foreground">Warnings ({executionSummary.warningCount})</summary>
              <div class="mt-3 space-y-2 text-sm text-muted-foreground">
                {#each executionSummary.warnings as item}
                  <div class="rounded-lg border border-border/50 bg-background/70 px-3 py-2">
                    <p class="font-medium text-foreground">{item.title || item.recommendation_id}</p>
                    <p>{item.message || "Blocked"}</p>
                  </div>
                {/each}
              </div>
            </details>

            <details class="rounded-xl border border-border/60 bg-background/50 p-3">
              <summary class="cursor-pointer font-medium text-foreground">Failures ({executionSummary.failedCount})</summary>
              <div class="mt-3 space-y-2 text-sm text-muted-foreground">
                {#each executionSummary.failed as item}
                  <div class="rounded-lg border border-border/50 bg-background/70 px-3 py-2">
                    <p class="font-medium text-foreground">{item.title || item.recommendation_id}</p>
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
          <h2 class="text-lg font-semibold text-foreground">Execution History</h2>
          {#if executionHistory && executionHistory.items.length > 0}
            <div class="mt-3 space-y-2 text-sm">
              {#each executionHistory.items.slice(0, 8) as row}
                <details class="rounded-xl border border-border/50 bg-background/70 px-3 py-3">
                  <summary class="cursor-pointer list-none">
                    <div class="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <p class="font-medium text-foreground">{row.action === "bulk_execute" ? "Operations Execution" : row.action}</p>
                        <p class="text-xs text-muted-foreground">
                          {row.selected_count} assets • {row.status} • {formatDuration(row.elapsed_ms)}
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
                      <div class="rounded-lg border border-border/40 bg-background/60 px-3 py-2">
                        <div class="flex items-center justify-between gap-2">
                          <span class="font-medium text-foreground">{item.title}</span>
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
            <p class="mt-2 text-sm text-muted-foreground">No execution history yet.</p>
          {/if}
        </div>

        <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
          <h2 class="text-lg font-semibold text-foreground">Audit Log</h2>
          {#if auditTrail && auditTrail.items.length > 0}
            <div class="mt-3 space-y-2 text-xs">
              {#each auditTrail.items.slice(0, 10) as row}
                <div class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/50 bg-background/70 px-3 py-2">
                  <span class="text-foreground">{row.action} • {row.target_type}#{row.target_id ?? "n/a"}</span>
                  <span class="text-muted-foreground">{row.result} • {formatFileSize(row.recovery_bytes)}</span>
                </div>
              {/each}
            </div>
          {:else}
            <p class="mt-2 text-sm text-muted-foreground">No operation history yet.</p>
          {/if}
        </div>
      </section>
    {/if}
  </div>
</div>
