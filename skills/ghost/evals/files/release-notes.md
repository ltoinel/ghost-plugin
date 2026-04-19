---
title: Release notes for v2.3
tags: [releases, engineering]
status: draft
excerpt: What shipped this sprint — faster search, a new admin dashboard, and a fix for tag filtering.
---

# Release notes for v2.3

We shipped three things this week that I wanted to flag.

## Faster search

Indexing now uses an inverted index on post bodies, cutting average query time from ~180ms to ~25ms on our corpus. No config changes required — it just works.

## New admin dashboard

Admins now see a single pane with content velocity, member growth, and the newsletter open-rate trend for the last 30 days. Replaces the three separate dashboards we had before.

## Bug fix: tag filtering

Tag filtering was accidentally case-sensitive, so `Engineering` and `engineering` showed up as different tags. Normalized everything to lowercase on write; existing posts have been backfilled.
