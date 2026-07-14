<script lang="ts">
  import { onMount } from "svelte";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import MovieCard from "$lib/design-system/cards/movie-card.svelte";
  import {
    createPreset,
    deletePreset,
    duplicatePreset,
    loadModuleDisplayState,
    renamePreset,
    resetModuleDisplayState,
    saveModuleDisplayState,
    updatePresetConfig,
  } from "$lib/design-system/display/profiles";
  import type {
    DisplayField,
    DisplayModuleId,
    DisplayProfileConfig,
    ModuleDisplayState,
  } from "$lib/design-system/display/types";
  import type { MovieObject } from "$lib/design-system/model/types";

  let {
    moduleId,
    open = $bindable(false),
    onSave,
  }: {
    moduleId: DisplayModuleId;
    open?: boolean;
    onSave?: (config: DisplayProfileConfig, state: ModuleDisplayState) => void;
  } = $props();

  let profileState: ModuleDisplayState = $state({ activePresetId: "default", presets: [] });
  let draft: DisplayProfileConfig | null = $state(null);

  const allFields: DisplayField[] = [
    "timeline",
    "recommendation_summary",
    "confidence",
    "risk",
    "recoverable_space",
    "filesystem",
    "protection",
    "ratio",
    "seed_days",
    "tracker",
    "progress",
  ];

  const activePreset = $derived.by(
    () => profileState.presets.find((item) => item.id === profileState.activePresetId) ?? null,
  );

  const effectiveConfig = $derived.by(() => draft ?? activePreset?.config ?? null);

  const previewObject = $derived.by((): MovieObject => {
    const config = effectiveConfig;
    return {
      id: "preview_movie",
      kind: "movie",
      title: "Preview: The Last Cleanup",
      subtitle: `${config?.viewMode ?? "cards"} • ${config?.cardDensity ?? "comfortable"}`,
      posterUrl: null,
      lifecycleState: "protected",
      recommendationSeverity: "action",
      recommendation: {
        message: "Action available: detach torrent and reclaim 12.4 GB.",
        confidence: 0.93,
        risk: "low",
      },
      healthSignals: [
        { kind: "protected", label: "Protected", explanation: "This media is user protected." },
        { kind: "filesystem_verified", label: "FS Verified", explanation: "Path mapping and file checks passed." },
        { kind: "torrent_active", label: "Torrent Active", explanation: "Torrent is currently active." },
      ],
      quickActions: [
        { id: "open", label: "Open" },
        { id: "details", label: "Details" },
        { id: "approve", label: "Approve" },
      ],
    };
  });

  const ensureDraft = (): DisplayProfileConfig => {
    if (draft) return draft;
    const next = activePreset?.config;
    if (!next) {
      throw new Error("No active display preset found");
    }
    draft = {
      ...next,
      visibleMetadata: [...next.visibleMetadata],
      visibleFields: [...next.visibleFields],
    };
    return draft;
  };

  const toggleField = (field: DisplayField, enabled: boolean): void => {
    const target = ensureDraft();
    const set = new Set(target.visibleFields);
    if (enabled) set.add(field);
    else set.delete(field);
    draft = { ...target, visibleFields: Array.from(set) };
  };

  const toggleMetadata = (field: string, enabled: boolean): void => {
    const target = ensureDraft();
    const set = new Set(target.visibleMetadata);
    if (enabled) set.add(field);
    else set.delete(field);
    draft = { ...target, visibleMetadata: Array.from(set) };
  };

  const setDraftValue = <K extends keyof DisplayProfileConfig>(key: K, value: DisplayProfileConfig[K]): void => {
    const target = ensureDraft();
    draft = { ...target, [key]: value };
  };

  const saveChanges = (): void => {
    const target = effectiveConfig;
    if (!target) return;
    profileState = updatePresetConfig(profileState, profileState.activePresetId, target);
    saveModuleDisplayState(moduleId, profileState);
    onSave?.(target, profileState);
    open = false;
  };

  const cancelChanges = (): void => {
    draft = null;
    open = false;
  };

  const resetToDefaults = (): void => {
    profileState = resetModuleDisplayState(moduleId);
    draft = null;
  };

  const addPreset = (): void => {
    const base = effectiveConfig;
    if (!base) return;
    const name = window.prompt("Preset name", "Custom preset");
    if (!name) return;
    profileState = createPreset(profileState, name, base);
    draft = null;
  };

  const renameActivePreset = (): void => {
    const preset = activePreset;
    if (!preset || preset.builtIn) return;
    const name = window.prompt("Rename preset", preset.name);
    if (!name) return;
    profileState = renamePreset(profileState, preset.id, name);
  };

  const duplicateActivePreset = (): void => {
    profileState = duplicatePreset(profileState, profileState.activePresetId);
    draft = null;
  };

  const deleteActivePreset = (): void => {
    profileState = deletePreset(profileState, profileState.activePresetId);
    draft = null;
  };

  const resetPreset = (): void => {
    draft = null;
  };

  onMount(() => {
    profileState = loadModuleDisplayState(moduleId);
  });
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-6xl border-ring border-2">
    <Dialog.Header>
      <Dialog.Title>Display Options</Dialog.Title>
      <Dialog.Description>
        Module profile: {moduleId}. Changes are isolated per module and persist independently.
      </Dialog.Description>
    </Dialog.Header>

    <div class="grid gap-5 p-2 md:grid-cols-[1.2fr_1fr]">
      <div class="space-y-4 rounded-2xl border border-border/70 bg-card p-4">
        <div class="grid gap-3 md:grid-cols-3">
          <div class="space-y-2">
            <div class="text-xs uppercase tracking-wide text-muted-foreground">Preset</div>
            <Select.Root type="single" value={profileState.activePresetId} onValueChange={(value) => { profileState = { ...profileState, activePresetId: value }; draft = null; }}>
              <Select.Trigger class="bg-background text-card-foreground">
                {activePreset?.name ?? "Select preset"}
              </Select.Trigger>
              <Select.Content class="bg-card">
                {#each profileState.presets as preset}
                  <Select.Item value={preset.id} label={preset.name} class="text-card-foreground">{preset.name}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
          </div>

          <div class="space-y-2">
            <div class="text-xs uppercase tracking-wide text-muted-foreground">View mode</div>
            <Select.Root
              type="single"
              value={effectiveConfig?.viewMode ?? "cards"}
              onValueChange={(value) => setDraftValue("viewMode", value as DisplayProfileConfig["viewMode"])}
            >
              <Select.Trigger class="bg-background text-card-foreground">{effectiveConfig?.viewMode ?? "cards"}</Select.Trigger>
              <Select.Content class="bg-card">
                <Select.Item value="cards" label="Cards" class="text-card-foreground">Cards</Select.Item>
                <Select.Item value="context_grid" label="Context Grid" class="text-card-foreground">Context Grid</Select.Item>
                <Select.Item value="diagnostics" label="Diagnostics" class="text-card-foreground">Diagnostics</Select.Item>
              </Select.Content>
            </Select.Root>
          </div>

          <div class="space-y-2">
            <div class="text-xs uppercase tracking-wide text-muted-foreground">Card density</div>
            <Select.Root
              type="single"
              value={effectiveConfig?.cardDensity ?? "comfortable"}
              onValueChange={(value) => setDraftValue("cardDensity", value as DisplayProfileConfig["cardDensity"])}
            >
              <Select.Trigger class="bg-background text-card-foreground">{effectiveConfig?.cardDensity ?? "comfortable"}</Select.Trigger>
              <Select.Content class="bg-card">
                <Select.Item value="comfortable" label="Comfortable" class="text-card-foreground">Comfortable</Select.Item>
                <Select.Item value="compact" label="Compact" class="text-card-foreground">Compact</Select.Item>
                <Select.Item value="dense" label="Dense" class="text-card-foreground">Dense</Select.Item>
              </Select.Content>
            </Select.Root>
          </div>
        </div>

        <div class="space-y-2">
          <div class="text-xs uppercase tracking-wide text-muted-foreground">Poster size</div>
          <input
            type="range"
            min="120"
            max="280"
            step="8"
            value={effectiveConfig?.posterSize ?? 176}
            oninput={(event) => {
              const target = event.currentTarget as HTMLInputElement;
              setDraftValue("posterSize", parseInt(target.value, 10));
            }}
            class="w-full accent-primary"
          />
        </div>

        <div class="grid gap-3 md:grid-cols-2">
          <label class="flex items-center gap-2 text-sm text-foreground"><input type="checkbox" checked={effectiveConfig?.visibleBadges ?? true} onchange={(event) => setDraftValue("visibleBadges", (event.currentTarget as HTMLInputElement).checked)} />Visible badges</label>
          <label class="flex items-center gap-2 text-sm text-foreground"><input type="checkbox" checked={effectiveConfig?.visibleRibbons ?? true} onchange={(event) => setDraftValue("visibleRibbons", (event.currentTarget as HTMLInputElement).checked)} />Visible ribbons</label>
          <label class="flex items-center gap-2 text-sm text-foreground"><input type="checkbox" checked={effectiveConfig?.visibleHealthStrip ?? true} onchange={(event) => setDraftValue("visibleHealthStrip", (event.currentTarget as HTMLInputElement).checked)} />Health strip</label>
          <label class="flex items-center gap-2 text-sm text-foreground"><input type="checkbox" checked={effectiveConfig?.hoverActions ?? true} onchange={(event) => setDraftValue("hoverActions", (event.currentTarget as HTMLInputElement).checked)} />Hover actions</label>
          <label class="flex items-center gap-2 text-sm text-foreground"><input type="checkbox" checked={effectiveConfig?.quickActions ?? true} onchange={(event) => setDraftValue("quickActions", (event.currentTarget as HTMLInputElement).checked)} />Quick actions</label>
        </div>

        <div class="space-y-2">
          <div class="text-xs uppercase tracking-wide text-muted-foreground">Visible metadata</div>
          <div class="flex flex-wrap gap-2">
            {#each ["title", "subtitle", "provider", "state", "space"] as field}
              <label class="inline-flex items-center gap-1 rounded-full border border-border/70 px-2 py-1 text-xs">
                <input
                  type="checkbox"
                  checked={effectiveConfig?.visibleMetadata.includes(field) ?? false}
                  onchange={(event) => toggleMetadata(field, (event.currentTarget as HTMLInputElement).checked)}
                />
                {field}
              </label>
            {/each}
          </div>
        </div>

        <div class="space-y-2">
          <div class="text-xs uppercase tracking-wide text-muted-foreground">Visible fields</div>
          <div class="grid gap-2 md:grid-cols-2">
            {#each allFields as field}
              <label class="flex items-center gap-2 text-xs text-foreground">
                <input
                  type="checkbox"
                  checked={effectiveConfig?.visibleFields.includes(field) ?? false}
                  onchange={(event) => toggleField(field, (event.currentTarget as HTMLInputElement).checked)}
                />
                {field.replaceAll("_", " ")}
              </label>
            {/each}
          </div>
        </div>

        <div class="flex flex-wrap gap-2 border-t border-border/70 pt-3">
          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs" onclick={addPreset}>Create</button>
          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs" onclick={renameActivePreset}>Rename</button>
          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs" onclick={duplicateActivePreset}>Duplicate</button>
          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs" onclick={deleteActivePreset}>Delete</button>
          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs" onclick={resetPreset}>Reset</button>
          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs" onclick={resetToDefaults}>Reset to Defaults</button>
        </div>
      </div>

      <div class="space-y-3 rounded-2xl border border-border/70 bg-card p-4">
        <div class="text-xs uppercase tracking-wide text-muted-foreground">Live preview</div>
        <MovieCard item={previewObject} posterSize={effectiveConfig?.posterSize ?? 176} />
        <div class="rounded-xl border border-border/70 bg-background/70 p-3 text-xs text-muted-foreground">
          <p>Timeline: {(effectiveConfig?.visibleFields.includes("timeline") ?? false) ? "Visible" : "Hidden"}</p>
          <p>Recommendation Summary: {(effectiveConfig?.visibleFields.includes("recommendation_summary") ?? false) ? "Visible" : "Hidden"}</p>
          <p>Risk: {(effectiveConfig?.visibleFields.includes("risk") ?? false) ? "Visible" : "Hidden"}</p>
          <p>Filesystem: {(effectiveConfig?.visibleFields.includes("filesystem") ?? false) ? "Visible" : "Hidden"}</p>
          <p>Progress: {(effectiveConfig?.visibleFields.includes("progress") ?? false) ? "Visible" : "Hidden"}</p>
        </div>
      </div>
    </div>

    <Dialog.Footer>
      <button type="button" class="rounded-full border border-border px-4 py-2 text-sm" onclick={cancelChanges}>Cancel</button>
      <button type="button" class="rounded-full border border-border px-4 py-2 text-sm" onclick={resetToDefaults}>Reset to Defaults</button>
      <button type="button" class="rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground" onclick={saveChanges}>Save</button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
