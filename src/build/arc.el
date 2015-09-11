;; Copyright (c) 2014 The Chromium Authors. All rights reserved.
;; Use of this source code is governed by a BSD-style license that can be
;; found in the LICENSE file.

;; Useful utilities when working with ARC in Emacs.

(defun arc--topdir ()
  "Obtain the top directory of arc checkout."
  (expand-file-name (locate-dominating-file default-directory "launch_chrome")))

(defun arc--replace-in-string (from to string)
  (replace-regexp-in-string (regexp-quote from) to string nil 'literal))

(defun arc--get-third-party ()
  "Get third_party version if possible, or return original if failing that."
  (let* ((topdir (arc--topdir))
         (arc-mod-track
          ;; Try to find the ARC MOD TRACK pattern.
          (save-excursion
            (beginning-of-buffer)
            (if (re-search-forward "ARC MOD TRACK \"\\(.*\\)\"" nil t)
                (concat (arc--topdir) (match-string 1))
              nil)))
         (third-party (or arc-mod-track
                          ;; If ARC MOD TRACK didn't exist, just
                          ;; replace path.
                          (arc--replace-in-string
                           (concat topdir "mods/")
                           (concat topdir "third_party/")
                           buffer-file-name))))
    third-party))

(defun arc--get-mods (filename)
  "Get mods version if possible, or return original if failing that."
  (let ((topdir (arc--topdir)))
    (arc--replace-in-string
     (concat topdir "third_party/")
     (concat topdir "mods/")
     filename)))

(defun arc-third-party ()
  "Go to third-party version."
  (interactive)
  (find-file (arc--get-third-party)))

(defun arc-mods ()
  "Go to mods version."
  (interactive)
  (find-file (arc--get-mods buffer-file-name)))

(defun arc-ediff ()
  "Run ediff between third_party/ and mods/."
  (interactive)
  (let* ((third-party (arc--get-third-party)))
    (ediff third-party
           (arc--get-mods buffer-file-name))))

(defun arc-copy-to-mods ()
  "Copy current file to mods/ directory for editing."
  (interactive)
  (write-file (arc--get-mods buffer-file-name)))

(defun arc-insert-bug (n)
  "Insert a bug comment at current position."
  (interactive "nBug ID: ")
  (comment-indent)
  (insert (concat "TODO(crbug.com/" (number-to-string n) "): ")))

;; Make Arc run_integration_tests run better, use like:
;; (add-to-list
;;     'comint-preoutput-filter-functions
;;     'arc-comint-filter-ansi-escape-position)
(defun arc-comint-filter-ansi-escape-position (output)
  "Remove the escape to position."
      (replace-regexp-in-string "\\[[0-9]+[GK]" "\r" output))

(defun arc-insert-mod-comment (useful-comment)
  "Insert a arc mod comment message."
  (interactive "MComment: ")
  (let* ((beginning-point (point)))
    (insert (concat "\n"
                    "ARC MOD BEGIN\n"
                    useful-comment "\n"
                    "ARC MOD END\n"))
    (comment-region beginning-point (point))))

(defun arc-insert-mod-with-file (filename)
  "Insert a arc mod with fork file."
  (interactive (list (read-file-name "fork file name: "
                                     (concat (arc--topdir) "mods/fork/"))))
  (let* ((beginning-point (point)))
    (insert (concat "\n"
                    "ARC MOD BEGIN " (file-name-nondirectory filename) "\n"
                    "ARC MOD END\n"))
    (comment-region beginning-point (point))
    (find-file-other-window filename)))

(defun arc-insert-mod-upstream (filename)
  "Insert a arc mod with upstream file."
  (interactive (list (read-file-name "upstream file name: "
                                     (concat (arc--topdir) "mods/upstream/"))))
  (let* ((beginning-point (point)))
    (insert (concat "\n"
                    "ARC MOD BEGIN UPSTREAM " (file-name-nondirectory filename) "\n"
                    "ARC MOD END UPSTREAM\n"))
    (comment-region beginning-point (point))
    (find-file-other-window filename)))
