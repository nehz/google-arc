LOCAL_PATH := $(call my-dir)
include $(CLEAR_VARS)

# libvpx
# if ARMv7 + NEON etc blah blah
# ARC MOD BEGIN UPSTREAM libvpx-fix-build-path
include $(LOCAL_PATH)/libvpx.mk
# ARC MOD END UPSTREAM

# libwebm
# ARC MOD BEGIN UPSTREAM libvpx-fix-build-path
include $(LOCAL_PATH)/libwebm.mk
# ARC MOD END UPSTREAM
