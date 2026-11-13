# GitHub Action

`action.yml` is a composite action. It installs this package and runs `python3 -m claimcheck.action` on the checked-out repository.

The example workflow is [example-workflow.yml](example-workflow.yml). It is not registered under `.github/workflows` in this repository, and it has not been run on GitHub. The tests call the same Python entry point with a recorded model response. They do not post a comment or call the GitHub API.

## What the action does

- Scans the workspace with the same verdict rules as `claimcheck scan`.
- Appends the report to the job summary (`GITHUB_STEP_SUMMARY`).
- Leaves a pull request comment off unless `comment` is `true`. When it is on, the action posts one comment or updates the comment that already contains `<!-- claimcheck-report -->`.
- `fail-on` defaults to `none`. Set it to `contradicted` to fail the job when any verdict is `contradicted`. `not_found` and `unverifiable` do not fail the job.
- When `base-sha` and `head-sha` are set and `git diff` can read them, the summary lists claims whose README line or cited evidence line is in that diff. If the diff cannot be read, the scan still finishes and the summary says the diff was skipped.

## API key

GitHub does not let an action read `secrets[name]` using a name chosen at runtime. The example workflow exports `secrets.CLAIMCHECK_API_KEY` into the environment variable `CLAIMCHECK_API_KEY`, and the input `api-key-secret-name` selects that variable. Change both places if the secret has another name. You can instead pass `api-key: ${{ secrets.YOUR_NAME }}` and leave the environment variable unset.

`model` has no default. A live model was not called from this action while it was added, because no API key was configured.

## Comment permission

The example requests `contents: read` only. Turn on comments by setting `comment: true` and adding `pull-requests: write`. Without that permission the comment step fails after the summary is written.
