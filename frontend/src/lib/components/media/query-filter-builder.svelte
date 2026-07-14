<script lang="ts">
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import type {
    QueryFilterCondition,
    QueryFilterGroup,
    QueryFilterNode,
  } from "$lib/types/shared";
  import Self from "./query-filter-builder.svelte";

  type Props = {
    node: QueryFilterNode;
    level?: number;
    onDelete?: (() => void) | null;
  };

  const conditionOperators = [
    { value: "equals", label: "Equals" },
    { value: "not_equals", label: "Does not equal" },
    { value: "contains", label: "Contains" },
    { value: "greater_than", label: "Greater than" },
    { value: "less_than", label: "Less than" },
    { value: "is_empty", label: "Is empty" },
    { value: "is_not_empty", label: "Is not empty" },
  ];

  let { node = $bindable(), level = 0, onDelete = null }: Props = $props();
  let currentCondition = $derived(node.type === "condition" ? node : null);
  let currentGroup = $derived(node.type === "group" ? node : null);

  const ensureGroup = () => {
    if (node.type === "group") return;
    const promoted: QueryFilterGroup = {
      type: "group",
      combinator: "and",
      clauses: [node],
    };
    node = promoted;
  };

  const addClause = (next: QueryFilterNode) => {
    if (node.type !== "group") return;
    node = {
      ...node,
      clauses: [...node.clauses, next],
    };
  };

  const removeClause = (index: number) => {
    if (node.type !== "group") return;
    node = {
      ...node,
      clauses: node.clauses.filter((_, clauseIndex) => clauseIndex !== index),
    };
  };

  const updateCondition = (key: keyof QueryFilterCondition, value: string) => {
    if (node.type !== "condition") return;
    node = {
      ...node,
      [key]: key === "value" ? value : value,
    } as QueryFilterCondition;
  };
</script>

{#if node.type === "condition"}
  <div
    class="rounded-lg border border-border/60 bg-background/80 p-3 space-y-3"
  >
    <div class="flex items-start justify-between gap-2">
      <div>
        <p
          class="text-xs font-medium uppercase tracking-wide text-muted-foreground"
        >
          Rule
        </p>
        <p class="text-sm text-card-foreground">
          Level {level + 1}
        </p>
      </div>
      {#if onDelete}
        <button
          type="button"
          class="text-xs text-muted-foreground hover:text-destructive cursor-pointer"
          onclick={onDelete}
        >
          Remove
        </button>
      {/if}
    </div>

    <div class="grid gap-2 md:grid-cols-[1.2fr_1fr_1.2fr]">
      <Input
        class="h-8 bg-card"
        value={currentCondition?.field ?? ""}
        placeholder="Field"
        oninput={(event) =>
          updateCondition("field", (event.target as HTMLInputElement).value)}
      />
      <Select.Root type="single" bind:value={currentCondition!.operator}>
        <Select.Trigger class="h-8 bg-card text-card-foreground">
          {conditionOperators.find(
            (option) => option.value === currentCondition?.operator,
          )?.label ?? currentCondition?.operator}
        </Select.Trigger>
        <Select.Content class="bg-card">
          {#each conditionOperators as option}
            <Select.Item
              value={option.value}
              label={option.label}
              class="text-card-foreground"
            >
              {option.label}
            </Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
      <Input
        class="h-8 bg-card"
        value={String(currentCondition?.value ?? "")}
        placeholder="Value"
        oninput={(event) =>
          updateCondition("value", (event.target as HTMLInputElement).value)}
      />
    </div>

    <div class="flex flex-wrap gap-2">
      <button
        type="button"
        class="rounded border border-border px-2 py-1 text-xs cursor-pointer hover:bg-secondary/50"
        onclick={ensureGroup}
      >
        Add nested group
      </button>
    </div>
  </div>
{:else if currentGroup}
  <div
    class={`rounded-xl border border-border/70 bg-card/80 p-3 space-y-3 ${level > 0 ? "ml-4" : ""}`}
  >
    <div class="flex items-center justify-between gap-2">
      <div>
        <p
          class="text-xs font-medium uppercase tracking-wide text-muted-foreground"
        >
          Group
        </p>
        <p class="text-sm text-card-foreground">Combine rules using AND / OR</p>
      </div>
      <div class="flex items-center gap-2">
        <Select.Root type="single" bind:value={currentGroup!.combinator}>
          <Select.Trigger class="h-8 bg-background text-card-foreground">
            {currentGroup.combinator.toUpperCase()}
          </Select.Trigger>
          <Select.Content class="bg-card">
            <Select.Item value="and" label="AND" class="text-card-foreground">
              AND
            </Select.Item>
            <Select.Item value="or" label="OR" class="text-card-foreground">
              OR
            </Select.Item>
          </Select.Content>
        </Select.Root>
        {#if onDelete}
          <button
            type="button"
            class="text-xs text-muted-foreground hover:text-destructive cursor-pointer"
            onclick={onDelete}
          >
            Remove group
          </button>
        {/if}
      </div>
    </div>

    <div class="space-y-3">
      {#each currentGroup.clauses as clause, index (index)}
        <div class="space-y-2">
          <Self
            bind:node={currentGroup.clauses[index]}
            level={level + 1}
            onDelete={() => removeClause(index)}
          />
        </div>
      {/each}
    </div>

    <div class="flex flex-wrap gap-2">
      <button
        type="button"
        class="rounded border border-border px-2 py-1 text-xs cursor-pointer hover:bg-secondary/50"
        onclick={() =>
          addClause({
            type: "condition",
            field: "",
            operator: "equals",
            value: "",
          })}
      >
        Add rule
      </button>
      <button
        type="button"
        class="rounded border border-border px-2 py-1 text-xs cursor-pointer hover:bg-secondary/50"
        onclick={() =>
          addClause({
            type: "group",
            combinator: currentGroup.combinator,
            clauses: [],
          })}
      >
        Add group
      </button>
      {#if level === 0}
        <button
          type="button"
          class="rounded border border-border px-2 py-1 text-xs cursor-pointer hover:bg-secondary/50"
          onclick={ensureGroup}
        >
          Promote to group
        </button>
      {/if}
    </div>
  </div>
{/if}
