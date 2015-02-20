Publishing a new version of the extension:

1) Make sure that the version number has been bumped in the manifest!

2) Zip up the extension:

    $ zip buildbot_watcher.zip src/build/buildbot_watcher/* -j -x \*README.txt

3) Visit the developer dashboard for the extension:

    https://chrome.google.com/webstore/developer/edit/lfpnafblenlngpflgnfnmmdfdofeoopo

  If this your first time, you may need to agree to some terms and conditions
  first.

4) Click the upload updated package button. On the next page select your .zip
   file and upload it.

5) Ensure the "Visibility Options" at the bottom are set to "Private" and
   "Everyone at google.com".

6) When everything looks good, publish the extension.
