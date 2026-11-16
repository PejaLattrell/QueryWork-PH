# Plan: collect job data and save it in Bronze

This is a future milestone for the [target architecture](architecture.MD). No job sites or other sources have been selected. The Python framework in `goodjob/ingestion/` has an empty source registry: collection and replay stop before ingestion HTTP or writes, even with a write key. Preservation, normalization, retry, and publication mechanisms are tested only with isolated fixtures. Source selection, adapter implementation, Databricks upload, and Bronze loading remain work to do. This plan recommends no provider or endpoint.

## Goal

First explicitly select a permitted input and implement/test its adapter. Then reuse the Python framework to preserve original responses in Databricks, retaining provenance, retrieval time, and separate collection/upload/Bronze-load outcomes. Those are distinct milestones, and none establishes Philippine coverage without source validation.

Bronze means the collection of originals. Cleaning salaries, deciding which jobs match the Philippines, removing repeated jobs, and calculating charts come later.

The first verified Databricks path will be:

Authorized source → Python collector → original response in a managed volume → Bronze.

## 1. Check the Databricks account

- Confirm which account edition is being used and where the project will store its data.
- Confirm we can run Python, create the two tables described below, and save and read a small test record.
- Check whether Python running inside Databricks can contact the first job source. Use a small request and count it toward that source's request allowance.
- Keep account keys out of project files and saved job responses. Use Databricks' protected settings for any private account access.

Databricks Free Edition restricts which websites it can contact. If the chosen source is blocked, run the collector outside Databricks, save its unchanged response to a local file, and upload it into Databricks. A Databricks program will read that file into the same Bronze table. Keep the local copy until the upload and table write are confirmed. We will document that route if it is needed.

Finish this check before choosing where the scheduled collector will run. Do not assume the local computer can stay switched off if it is doing the collection.

## 2. Start with one source

Choose one source that allows automated collection and reuse at no cost. Prefer an authorized feed or API. Check its terms, request limits, authentication, and available identifiers before testing a fetch.

Record the filters and limits used by each collection. Preserve the original response, including source links and notices. Source selection and any claims about geographic coverage require separate validation.

## 3. Define landing and Bronze records

**Original responses:** one landed file for each saved response from a source. Store the following metadata alongside the response. One response can contain many job listings.

| Information | Why we keep it |
| --- | --- |
| Collection label | Connects this response to the attempt that collected it |
| Source name and request address | Shows where the data came from and what was requested |
| Request label or page number | Distinguishes requests within the same collection |
| Time received | Shows when we observed the data |
| Website's reply code and content type | Helps distinguish job data from errors |
| Complete original response text | Preserves the source's fields and wording for later work |
| Content check value | Lets us confirm the saved response matches the received text |

**Collection history:** one row for each collection attempt, recording its label, start and finish times, source, result, requests made, responses saved, jobs reported by the response when readable, and a useful error explanation if it failed. Keep the source's job publication times separate from our collection time.

Keep original batches in the managed landing volume for replay. For Bronze postings, use source, stable source job ID (or canonical listing URL), and a stable content hash as the version key. Repeated observations belong in collection history and do not require another posting version. Preserve changed versions.

## 4. Reuse the collector and implement the Databricks saving step

The CLI is `python -m ingestion` from `goodjob/`, with `--help` available. It currently reports that no sources are selected and exits 2 before settings, ingestion HTTP, landing output, or database writes. Replay is guarded in the same way. After an adapter is explicitly chosen and implemented, the prepared archive contract uses `.local/ingestion/<run-uuid>` by default; fixture tests cover preservation, checksums, and replay without source refetching. Extend that framework contract with a volume uploader and loader while keeping normalization after preservation. Local archives or Supabase writes alone would not satisfy this Databricks milestone.

- Give each collection a unique label before requesting data.
- Set a maximum waiting time for a website response.
- Capture the complete response text before inspecting its contents.
- Save that original text with the information above. Do not change salaries, rename locations, remove repeated listings, or discard unfamiliar fields.
- Check whether the response is readable and contains the expected list of jobs. Keep unexpected response text too, but report the collection as failed or needing investigation.
- Count jobs only when the response can be read. Do not confuse the number of saved responses with the number of jobs.
- Read the saved response back and compare it with the received text before marking the collection successful.

## 5. Make failures and retries understandable

- Retry temporary connection errors a limited number of times, with pauses that respect the source's allowance and any requested waiting period.
- Stop retrying errors that require a change, such as denied access or an invalid request.
- Once a response has been saved, reuse that saved copy if a later step fails. Do not contact the website again just to repeat a table write or finish the history record.
- A retry of the same saved response uses the same collection and request labels, so it does not create a second copy. Run only one collection at a time initially.
- If the response write succeeds but updating collection history fails, check the saved response when recovering and finish the history record without collecting it again.
- A later scheduled collection gets a new label and keeps its own observation, even if the returned jobs are unchanged.
- An empty job list can be a successful collection. An error page cannot.
- If the program stops unexpectedly, leave the previous originals available and make an unfinished collection visible in the history.

## 6. Prove the first manual collection works

We will inspect the result inside Databricks and confirm:

- The response came from the real source, rather than the project's sample data.
- The complete original response can be read back without changes.
- The source, collection time, and request details are present.
- The saved response and reported job count agree.
- Repeating the saving step for the same response creates no extra copy.
- A later collection preserves the earlier response.
- An empty response, an error page, a connection timeout, and an interrupted save produce understandable results.
- A failed collection can be recovered without changing earlier originals.

Use saved examples for most failure checks so tests do not repeatedly call the real website.

## 7. Add a schedule after the manual checks pass

If collection can run inside Databricks, schedule it with Lakeflow Jobs. Consider an eight-hour interval after confirming source limits, including retries and manual tests, and measuring Free Edition compute usage.

If collection must run elsewhere, first document where it will run and how files will reach Databricks. Do not mark automatic collection complete until that whole route has worked on a schedule.

Provide a short guide showing how to run a collection, inspect its saved originals, find failures, retry safely, and pause the schedule.

## Work to add to this project

- Explicit source selection, collection/reuse and request-limit validation, and a fixture-tested adapter; no source is selected by this plan.
- A Databricks uploader for the Python framework's original bytes and metadata, with protected workspace settings.
- A Databricks setup file that creates the two tables without replacing existing data.
- A Databricks program that saves original responses and collection history.
- Checks for preservation, retries, and failure recovery.
- Setup and operating instructions, including scheduling and the first successful collection evidence.

This milestone can stop when a real response is stored and readable in Bronze, repeat attempts behave correctly, failures are visible, and the chosen scheduled route has succeeded. Silver, Gold, and the future snapshot publisher follow in later work. No Databricks or hosted schedule has been enabled by the local Python implementation.

## References

- [Databricks Bronze guidance](https://docs.databricks.com/aws/en/lakehouse/medallion)
- [Databricks Free Edition limits](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations)
- [Databricks scheduling](https://docs.databricks.com/aws/en/jobs/scheduled)
