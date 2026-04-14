# Week 1 — Gmail Triage Setup and Manual Workflow

## Purpose

The goal of this first step is to set up a simple, repeatable manual workflow for testing AI-assisted email triage in ChatGPT.

This is **not** an automation phase.

By the end of this phase, the system achieved a repeatable Gmail triage workflow that can:

- classify Gmail threads
- summarize priorities
- identify the current status of a conversation
- surface the latest useful next action
- draft reply suggestions for threads that need a response
- track follow-ups for daily review

---

## Scope

This first step focuses only on:

- connecting Gmail to ChatGPT, if available
- testing a small batch of real emails
- defining categories
- creating a small prompt library
- logging what works and what fails

Future CRM integration, including HubSpot, is **out of scope for this week**.

---

## Week 1 Deliverables

By the end of this step, the following should exist:

- a working project note or document
- a defined category system
- a small prompt library
- at least 2 to 3 real tests completed
- an evaluation log with observations
- a short Week 1 summary

---

## Project Files / Working Sections

Create one working document called:

`Inter-Op Email Workflow v1`

Inside it, include these sections:

### 1. Email Workflow v1
Describe the workflow being tested and the purpose of the experiment.

### 2. Prompt Library
Store the prompts being tested.

### 3. Category Definitions
Store the email classification categories and their meanings.

### 4. Evaluation Log
Track what worked, what failed, and what should change.

---

## Category Definitions

Use the following fixed categories for Week 1:

- **Urgent / Executive**  
  Emails requiring same-day attention, leadership visibility, or immediate action.

- **Customer / Partner**  
  External relationship emails, customer communication, partner follow-ups, and business development messages.

- **Events / Logistics**  
  Scheduling, travel, shipping, coordination, event-related items, and operational logistics.

- **Finance / Admin**  
  Invoices, payments, administrative matters, HR/admin, and internal process emails.

- **FYI / Low Priority**  
  Informational updates, newsletters, or low-urgency items that do not require immediate action.

---

## Step-by-Step Instructions

### Step 1 — Create the working document

Create a document with the following title:

`Inter-Op Email Workflow v1`

Add these sections:

- Email Workflow v1
- Prompt Library
- Category Definitions
- Evaluation Log

---

### Step 2 — Connect Gmail to ChatGPT

If supported by the workspace or plan:

1. Open ChatGPT
2. Go to **Settings**
3. Open **Apps**, **Connectors**, or **Connected Apps**
4. Connect Gmail / Google account
5. Confirm access is working

If Gmail is unavailable, document the blocker and continue with copied email samples instead.

Example blocker note:

```text
Blocked:
Gmail connector not available in current plan/workspace settings.

Next action:
Confirm with admin whether Google connectors are enabled.
