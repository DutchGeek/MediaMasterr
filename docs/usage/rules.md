# Rules

Cleanup rules determine which media becomes a reclaim candidate. A rule has:

- a target scope
- one or more conditions
- nested `AND` or `OR` groups
- an action to perform after the candidate is approved

Use rule preview before saving or running a cleanup scan. Preview shows the
items that match and the actual values used for each matching condition.

## Target Scopes

Fields are limited to scopes where Reclaimerr has meaningful data.

| Scope | Evaluated item | Examples |
| --- | --- | --- |
| Movie version | One physical movie file | Container, bitrate, codec, subtitles |
| Series | The complete local series | Status, year, season counts |
| Season | One local season | Season number, episode count, inherited series metadata |
| Episode | One local episode | Episode number, air date, inherited series metadata |

A movie-version rule evaluates each physical version independently. If a movie
has multiple files, more than one version can become a candidate.

## Condition Groups

An `AND` group matches only when every child condition matches. An `OR` group
matches when at least one child condition or child group matches.

For example, this identifies old, unwatched movies that are either large or
have multiple versions:

```text
AND
  Never watched is true
  Days since added >= 180
  OR
    Size > 21474836480
    Movie version count > 1
```

`21474836480` is 20 GiB expressed in bytes, which is the unit expected by the
size field.

## Operators

### List Operators

| Internal operator | UI label | Meaning |
| --- | --- | --- |
| `contains_any` | matches any | At least one supplied value matches |
| `not_contains_any` | matches none | None of the supplied values match |
| `contains_all` | matches all | Every supplied value matches |
| `not_contains_all` | does not match all | At least one supplied value does not match |

Text and list comparisons are case-insensitive unless a field documents
additional normalization.

### Missing Values

`exists` matches populated metadata. `does not exist` matches missing or empty
metadata.

Missing metadata does not automatically prove a negative condition. Language
and origin-country rules therefore fail closed: if the item's value is unknown,
`matches none` and `does not match all` do not match it. Use a separate `does
not exist` condition when you specifically want to identify missing metadata.

## Field Reference

The rule editor only displays fields valid for the selected scope. The
following fields have behavior or units that are important when constructing a
rule.

### General Media Fields

| Field | Scope | Value |
| --- | --- | --- |
| Year | All scopes | Movie year or the parent series year |
| Size | All scopes | Bytes for the evaluated file, series, season, or episode |
| Duration | Movie version | Media-server duration in milliseconds |
| Container | Movie version | File container such as `mkv` or `mp4` |
| Path / Filename | All scopes | Local media-server path information |

### TMDB Metadata

| Field | Scope | Value |
| --- | --- | --- |
| Original language | All scopes | Canonical ISO 639-3 language code |
| Origin country | All scopes | Case-insensitive country code such as `US` or `JP` |
| Runtime | Movie version | TMDB movie runtime in minutes |
| Genres | All scopes | TMDB genre names |
| Rating / Votes / Popularity | All scopes | Current stored TMDB metadata |
| Release date | Movie version | Movie release date |
| First / last air date | Series, season, episode | Dates inherited from the parent series |

Original-language values are normalized before comparison. For example, `en`,
`eng`, and `English` all compare as `eng`. The picker displays languages found
in the local database, but manual entry remains available.

Origin-country comparisons are case-insensitive. The country picker displays
codes currently found in local TMDB metadata.

### Movie-Version Metadata

| Field | Unit or value |
| --- | --- |
| Video bitrate | Kilobits per second (`kbps`) |
| Audio bitrate | Kilobits per second (`kbps`) |
| Video bit depth | Bits, commonly `8`, `10`, or `12` |
| Subtitle track count | Number of subtitle streams |
| Has forced subtitles | Boolean |
| Movie version count | Number of physical versions stored for the movie |

Plex bitrate values are already stored as `kbps`. Jellyfin and Emby commonly
report bits per second, so Reclaimerr converts those values to `kbps` during
rule evaluation. This provides the same rule units across media servers without
rewriting stored metadata.

`Movie version count` is inherited by every version of the movie. A condition
such as `Movie version count > 1` therefore selects every version of each
multi-version movie. Combine it with a distinguishing condition such as
quality, codec, resolution, size, bitrate, container, or path when you intend
to remove only one version.

### Series Season Counts

| Field | Meaning |
| --- | --- |
| TMDB season count | Number of seasons reported by TMDB |
| Library season count | Number of locally stored seasons, excluding season 0 |

Season 0 is normally used for specials and is intentionally excluded from the
library season count. Both count fields are available to series, season, and
episode rules and are inherited from the parent series.

These values may differ when the local library contains only part of a series,
TMDB metadata has changed, or specials are present.

## Validation and Editing

- Operator choices are limited to operators supported by the selected field.
- Field choices are limited to the selected target scope.
- Changing a field resets an incompatible operator to the field's default.
- Existing saved rules are not rewritten until they are edited and saved.
- Backend validation rejects unsupported field, operator, or scope
  combinations.
- Rule preview uses the same evaluation logic as cleanup candidate scans.

## Recommended Workflow

1. Select the narrowest target scope that represents the intended deletion.
2. Add positive conditions that identify the media.
3. Add quality, age, watch-history, or metadata conditions to reduce broad
   matches.
4. Preview the rule and inspect the displayed actual values.
5. Save the rule only after the preview contains the intended files.
6. Run a candidate scan before enabling automatic actions.

## Related Pages

- [How It Works](how-it-works.md)
- [Tasks](tasks.md)
- [API Reference](../reference/api.md)
