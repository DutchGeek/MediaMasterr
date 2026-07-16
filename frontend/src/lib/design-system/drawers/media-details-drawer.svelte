<script lang="ts">
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import EpisodeCard from "$lib/design-system/cards/episode-card.svelte";
  import ArtworkImage from "$lib/design-system/media/artwork-image.svelte";
  import type {
    DetailsDrawerSection,
    MediaObject,
  } from "$lib/design-system/model/types";

  let {
    open = $bindable(false),
    item,
    sections = [],
  }: {
    open?: boolean;
    item: MediaObject | null;
    sections?: DetailsDrawerSection[];
  } = $props();
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-6xl border-ring border-2 max-h-[92vh] overflow-hidden">
    <Dialog.Header class="sticky top-0 z-10 bg-background/95 backdrop-blur border-b border-border/50 pb-3">
      <Dialog.Title>{item?.title ?? "Details"}</Dialog.Title>
      <Dialog.Description>
        Technical workspace for diagnostics, lifecycle, and provider detail.
      </Dialog.Description>
    </Dialog.Header>

    {#if item}
      <div class="grid gap-4 p-2 md:grid-cols-[1fr_1.3fr] max-h-[76vh] overflow-hidden">
        <div class="space-y-4 rounded-2xl border border-border/70 bg-card p-4 overflow-y-auto">
          <div class="text-xs uppercase tracking-wide text-muted-foreground">
            Artwork
          </div>
          <div
            class="overflow-hidden rounded-xl border border-border/70 bg-background/70 aspect-[2/3]"
          >
            <ArtworkImage
              src={item.posterUrl}
              alt={item.title}
              class="h-full w-full"
              imageClass="h-full w-full object-cover"
            />
          </div>

          {#if item.kind === "season" && item.episodes && item.episodes.length > 0}
            <div class="space-y-2">
              <div
                class="text-xs uppercase tracking-wide text-muted-foreground"
              >
                Episode Cards
              </div>
              <div class="space-y-2">
                {#each item.episodes as episode}
                  <EpisodeCard item={episode} posterSize={120} />
                {/each}
              </div>
            </div>
          {/if}
        </div>

        <div class="space-y-3 overflow-y-auto pr-1">
          {#each sections as section}
            <section class="rounded-2xl border border-border/70 bg-card p-4">
              <h3 class="text-sm font-semibold text-foreground">
                {section.title}
              </h3>
              {#if section.description}
                <p class="mt-1 text-xs text-muted-foreground">
                  {section.description}
                </p>
              {/if}
              {#if section.rows && section.rows.length > 0}
                <div
                  class="mt-3 overflow-x-auto rounded-xl border border-border/60"
                >
                  <table class="w-full min-w-[360px] text-xs">
                    <tbody>
                      {#each section.rows as row}
                        <tr class="border-b border-border/40 last:border-b-0">
                          <td class="px-3 py-2 text-muted-foreground"
                            >{row.key}</td
                          >
                          <td class="px-3 py-2 text-foreground">{row.value}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              {/if}
            </section>
          {/each}
        </div>
      </div>
    {/if}
  </Dialog.Content>
</Dialog.Root>
