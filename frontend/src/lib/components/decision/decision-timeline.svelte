<script lang="ts">
  import type { DecisionInfo } from "$lib/types/shared";

  interface Props {
    decision: DecisionInfo | null;
  }

  let { decision }: Props = $props();

  const stepTone = (status: string): string => {
    switch (status) {
      case "complete":
        return "bg-emerald-500 border-emerald-400";
      case "current":
        return "bg-primary border-primary";
      case "pending":
        return "bg-muted border-border";
      case "blocked":
        return "bg-red-500 border-red-400";
      default:
        return "bg-muted border-border";
    }
  };
</script>

{#if decision && decision.timeline.length > 0}
  <div class="space-y-3">
    {#each decision.timeline as step, index (step.key)}
      <div class="flex gap-3">
        <div class="flex flex-col items-center shrink-0">
          <span
            class={`mt-0.5 size-3 rounded-full border ${stepTone(step.status)}`}
          ></span>
          {#if index < decision.timeline.length - 1}
            <span class="mt-1 h-full min-h-6 w-px bg-border"></span>
          {/if}
        </div>
        <div class="min-w-0 pb-2 flex-1">
          <p class="text-sm font-medium text-foreground">{step.label}</p>
          {#if step.detail}
            <p class="text-xs text-muted-foreground mt-0.5">{step.detail}</p>
          {/if}
          {#if step.progress_percent != null}
            <div class="mt-2 h-2 w-full rounded-full bg-muted overflow-hidden">
              <div
                class="h-full bg-primary transition-[width] duration-300"
                style={`width: ${Math.max(0, Math.min(100, step.progress_percent))}%`}
              ></div>
            </div>
          {/if}
        </div>
      </div>
    {/each}
  </div>
{/if}
