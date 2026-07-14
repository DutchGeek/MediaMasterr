import { builtInPresets } from "$lib/design-system/display/defaults";
import type {
  DisplayModuleId,
  DisplayPreset,
  DisplayProfileConfig,
  ModuleDisplayState,
} from "$lib/design-system/display/types";

const keyFor = (moduleId: DisplayModuleId): string => `mediamasterr_display_profile_${moduleId}`;

const cloneConfig = (config: DisplayProfileConfig): DisplayProfileConfig => ({
  ...config,
  visibleMetadata: [...config.visibleMetadata],
  visibleFields: [...config.visibleFields],
});

const clonePreset = (preset: DisplayPreset): DisplayPreset => ({
  ...preset,
  config: cloneConfig(preset.config),
});

const buildFallback = (moduleId: DisplayModuleId): ModuleDisplayState => {
  const presets = builtInPresets(moduleId).map(clonePreset);
  return {
    activePresetId: presets[0]?.id ?? "default",
    presets,
  };
};

export const loadModuleDisplayState = (moduleId: DisplayModuleId): ModuleDisplayState => {
  try {
    const raw = localStorage.getItem(keyFor(moduleId));
    if (!raw) return buildFallback(moduleId);
    const parsed = JSON.parse(raw) as ModuleDisplayState;
    if (!parsed || !Array.isArray(parsed.presets) || !parsed.activePresetId) {
      return buildFallback(moduleId);
    }
    const merged = buildFallback(moduleId);
    const custom = parsed.presets.filter((item) => !item.builtIn).map(clonePreset);
    merged.presets = [...merged.presets, ...custom];
    const exists = merged.presets.some((item) => item.id === parsed.activePresetId);
    merged.activePresetId = exists ? parsed.activePresetId : merged.activePresetId;
    return merged;
  } catch {
    return buildFallback(moduleId);
  }
};

export const saveModuleDisplayState = (
  moduleId: DisplayModuleId,
  state: ModuleDisplayState,
): void => {
  localStorage.setItem(keyFor(moduleId), JSON.stringify(state));
};

export const resetModuleDisplayState = (moduleId: DisplayModuleId): ModuleDisplayState => {
  const fallback = buildFallback(moduleId);
  saveModuleDisplayState(moduleId, fallback);
  return fallback;
};

export const updatePresetConfig = (
  state: ModuleDisplayState,
  presetId: string,
  nextConfig: DisplayProfileConfig,
): ModuleDisplayState => {
  return {
    ...state,
    presets: state.presets.map((item) =>
      item.id === presetId ? { ...item, config: cloneConfig(nextConfig) } : item,
    ),
  };
};

export const duplicatePreset = (
  state: ModuleDisplayState,
  presetId: string,
): ModuleDisplayState => {
  const source = state.presets.find((item) => item.id === presetId);
  if (!source) return state;
  const copy: DisplayPreset = {
    ...clonePreset(source),
    id: `${presetId}_${Math.random().toString(36).slice(2, 8)}`,
    name: `${source.name} Copy`,
    builtIn: false,
  };
  return {
    ...state,
    activePresetId: copy.id,
    presets: [...state.presets, copy],
  };
};

export const renamePreset = (
  state: ModuleDisplayState,
  presetId: string,
  newName: string,
): ModuleDisplayState => {
  return {
    ...state,
    presets: state.presets.map((item) =>
      item.id === presetId && !item.builtIn ? { ...item, name: newName } : item,
    ),
  };
};

export const createPreset = (
  state: ModuleDisplayState,
  name: string,
  config: DisplayProfileConfig,
): ModuleDisplayState => {
  const preset: DisplayPreset = {
    id: `custom_${Math.random().toString(36).slice(2, 8)}`,
    name,
    builtIn: false,
    config: cloneConfig(config),
  };
  return {
    ...state,
    activePresetId: preset.id,
    presets: [...state.presets, preset],
  };
};

export const deletePreset = (state: ModuleDisplayState, presetId: string): ModuleDisplayState => {
  const target = state.presets.find((item) => item.id === presetId);
  if (!target || target.builtIn) return state;
  const presets = state.presets.filter((item) => item.id !== presetId);
  const fallbackId = presets[0]?.id ?? "default";
  return {
    ...state,
    activePresetId: state.activePresetId === presetId ? fallbackId : state.activePresetId,
    presets,
  };
};
