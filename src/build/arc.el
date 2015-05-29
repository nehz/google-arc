;; Copyright (c) 2014 The Chromium Authors. All rights reserved.
;; Use of this source code is governed by a BSD-style license that can be
;; found in the LICENSE file.

;; Useful utilities when working with ARC in Emacs.

(defun arc--topdir ()
  "Obtain the top directory of arc checkout."
  (locate-dominating-file default-directory "launch_chrome"))

(defun arc--get-third-party (filename)
  "Get third_party version if possible, or return original if failing that."
  (let* ((arc-mod-track
          ;; Try to find the ARC MOD TRACK pattern.
          (save-excursion
            (beginning-of-buffer)
            (if (re-search-forward "ARC MOD TRACK \"\\(.*\\)\"" nil t)
                (concat (arc--topdir) (match-string 1))
              nil)))
         (third-party (or arc-mod-track
                          ;; If ARC MOD TRACK didn't exist, just
                          ;; replace path.
                          (replace-regexp-in-string
                           "/mods/" "/third_party//" buffer-file-name))))
    third-party))

(defun arc--get-mods (filename)
  "Get mods version if possible, or return original if failing that."
  (replace-regexp-in-string
   "/third_party/" "/mods/" filename))

(defun arc-third-party ()
  "Go to third-party version."
  (interactive)
  (find-file (arc--get-third-party buffer-file-name)))

(defun arc-mods ()
  "Go to mods version."
  (interactive)
  (find-file (arc--get-mods buffer-file-name)))

(defun arc-ediff ()
  "Run ediff between third_party/ and mods/."
  (interactive)
  (let* ((third-party (arc--get-third-party buffer-file-name)))
    (ediff third-party
           (arc--get-mods buffer-file-name))))

(defun arc-copy-to-mods ()
  "Copy current file to mods/ directory for editing."
  (interactive)
  (write-file (arc--get-mods buffer-file-name)))

(defun arc-insert-l-rebase-bug ()
  "Insert a bug message at current position."
  (interactive)
  (comment-indent)
  (insert "TODO(crbug.com/414569): L-rebase:"))

;; Make Arc run_integration_tests run better, use like:
;; (add-to-list
;;     'comint-preoutput-filter-functions
;;     'arc-comint-filter-ansi-escape-position)
(defun arc-comint-filter-ansi-escape-position (output)
  "Remove the escape to position."
      (replace-regexp-in-string "\\[[0-9]+[GK]" "\r" output))

(defun arc-insert-mod-comment ()
  "Insert a arc mod comment message."
  (interactive)
  (let* ((beginning-point (point)))
    (insert (concat "\n"
                    "ARC MOD BEGIN\n"
                    "useful comment\n"
                    "ARC MOD END\n"))
    (comment-region beginning-point (point))))
