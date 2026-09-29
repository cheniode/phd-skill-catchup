# OpenAlex API quick reference

Read this when you cannot run the helper scripts and need to fetch OpenAlex URLs directly
with a web-fetch tool, or when you need something the scripts do not cover.

Base URL: `https://api.openalex.org`. All responses are JSON. No login is needed for light
use. If the user has an API key, append `&api_key=KEY`.

## Contents

1. Costs and limits
2. Load a researcher's works from an ORCID iD
3. Look up works by DOI or title
4. Find recent works on a topic
5. Reading a work record
6. Troubleshooting

## 1. Costs and limits

| Request | Cost |
|---|---|
| Filter or list request (no text search) | $0.0001 |
| Text search (`search`, `*.search` filters, `search.semantic`) | $0.001 |

The anonymous daily allowance is about $0.10, with a free API key it is higher. Response
headers `X-RateLimit-Remaining-USD` and `X-RateLimit-Limit-USD` show the balance.

HTTP 429 has two causes. Read the message in the response body:

- A short throttle. Anonymous text searches are throttled when the service is busy, and
  queries with more than 5 boolean operators are limited to one per second. The body and
  the `Retry-After` header give the number of seconds to wait. Wait, then repeat the request.
- The daily allowance is used up. Waiting does not help until the next day.

A free API key avoids the throttle and raises the allowance. Always add `select=` to keep responses small, and
`per-page=` (max 100) to control the number of results.

## 2. Load a researcher's works from an ORCID iD

Identify the person (one ORCID may map to more than one OpenAlex author profile):

```
/authors?filter=orcid:0000-0002-1825-0097&select=id,display_name,works_count,last_known_institutions
```

Load their works, newest first:

```
/works?filter=author.orcid:0000-0002-1825-0097&sort=publication_date:desc&per-page=100
      &select=id,doi,title,publication_date,publication_year,type,primary_topic,topics,keywords,primary_location,cited_by_count
```

For more than 100 works, add `&cursor=*` and pass `meta.next_cursor` from each response as
the next `cursor` value.

If OpenAlex knows nothing about the ORCID, the public ORCID record lists titles and DOIs:
`https://pub.orcid.org/v3.0/0000-0002-1825-0097/works` with header `Accept: application/json`.

## 3. Look up works by DOI or title

```
/works/doi:10.1111/lang.12232
/works?filter=doi:10.1111/lang.12232|10.1145/3845797          (up to 50, separated by |)
/works?filter=title.search:task effects on linguistic complexity and accuracy&per-page=3
```

Remove commas and `|` from titles first, because they are filter separators. Check that the
returned title really matches before using the record.

## 4. Find recent works on a topic

Keyword search in titles and abstracts, restricted to a date window:

```
/works?filter=title_and_abstract.search:"second language" AND (LLM OR "large language model"),
       from_publication_date:2026-06-30,to_publication_date:2026-09-28,
       is_retracted:false,type:article|preprint|review
      &per-page=25
      &select=id,doi,title,publication_date,type,primary_topic,keywords,primary_location,authorships,open_access,cited_by_count,abstract_inverted_index
```

(Write the filter on one line and URL-encode it. It is wrapped here for reading.)

- Search syntax: `"exact phrase"`, `AND`, `OR`, `NOT` in uppercase, parentheses.
- Default order is relevance. Add `&sort=publication_date:desc` or `&sort=cited_by_count:desc`
  to change it.
- Restrict to an OpenAlex topic with `topics.id:T11587` in the filter.
- Always set `to_publication_date` to today. Some records carry future dates.
- Prefer `title_and_abstract.search` over the general `search=` parameter, which also
  matches full text and returns many papers that only mention the terms in passing.

Works that cite the user's publications (a filter request, so cheap and not throttled):

```
/works?filter=cites:W2560647685|W2626778328,from_publication_date:2026-06-30,to_publication_date:2026-09-28
      &sort=publication_date:desc&per-page=50&select=...
```

Up to 50 work ids per request, separated by `|`.

Semantic search finds works by meaning instead of keywords:

```
/works?search.semantic=automatic feedback on second language writing with large language models
      &filter=publication_year:2026&per-page=50&select=...
```

It does not accept date filters, only `publication_year` (and a few others such as `type`,
`language`, `is_oa`). Filter the results by `publication_date` yourself.

## 5. Reading a work record

| Field | Meaning |
|---|---|
| `title`, `doi`, `publication_date`, `type` | basics. `type` is e.g. article, preprint, review, book-chapter |
| `authorships[].author.display_name` | authors in order. `authorships[].institutions[].display_name` for affiliations |
| `primary_location.source.display_name` | journal, conference or repository |
| `primary_topic`, `topics[]` | OpenAlex topic classification with `id`, `display_name`, `subfield`, `field`. Coarse (about 4,500 topics) |
| `keywords[]` | automatic keywords with scores. Noisy, low scores are often wrong |
| `open_access.is_oa`, `open_access.oa_url` | open access status and link |
| `abstract_inverted_index` | the abstract, stored as `{word: [positions]}` |

To rebuild the abstract, place every word at each of its positions and join them in
position order. Example: `{"We": [0], "show": [1], "that": [2]}` becomes "We show that".
A missing or null index means OpenAlex has no abstract for the work.

## 6. Troubleshooting

| Problem | What to do |
|---|---|
| HTTP 429 | See section 1. Wait the stated seconds and retry. If the allowance is used up, ask the user for a free API key (https://openalex.org/settings/api) or continue tomorrow |
| HTTP 400 "Invalid query parameters" | The message names the unsupported filter. Commas inside search text are a common cause |
| Thousands of matches | Add a constraining term or a `topics.id` filter |
| No matches | Check the date window, drop terms, add synonyms with OR, try semantic search |
| The same paper twice | Preprint and published version are separate records. Keep the published one |
