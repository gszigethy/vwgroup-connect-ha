# Volkswagen Android app version notifications

The fork's **Volkswagen Android app version watch** checks the public Google Play
listing for `com.volkswagen.weconnect` every day at **06:27 UTC**. In Budapest this
is 08:27 during summer time and 07:27 during winter time. You can also run it from
GitHub Actions using **Run workflow**; enable **dry_run** to check without creating
an issue.

A newer numeric version opens an issue containing the app version, package,
Google Play link, verified baseline and check time. The initial baseline is
**4.6.4**. After testing a newer APK, optionally set the repository Actions
variable **VW_ANDROID_BASELINE_VERSION** to that version.

The watcher checks all existing notifications, including closed issues, so a
version is reported once. Stale listings cannot cause a downgrade notification.
Deleting notification issues removes that history. Lookups without a valid
version fail the workflow instead of opening a misleading issue.

The source is the public US Google Play listing. Staged rollouts and device or
country differences mean a reported version may not yet be offered on your
phone. No VW credentials, phone connection, APK download, installation, vehicle
request, or integration release is involved. The workflow is restricted to
`gszigethy/vwgroup-connect-ha` and uses the built-in GitHub token with issue-write
permission; no additional secret is required.

Local read-only check:

```bash
python scripts/watch_vw_android.py --repo gszigethy/vwgroup-connect-ha --dry-run
```
