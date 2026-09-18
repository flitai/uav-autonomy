#ifndef UXAS_BRIDGE_FEATURES_H
#define UXAS_BRIDGE_FEATURES_H

// Existing Makefile users retain both bridges. The Windows CMake target
// explicitly supplies numeric 0/1 values, so use #if rather than #ifdef.
#ifndef UXAS_ENABLE_ZYRE
#define UXAS_ENABLE_ZYRE 1
#endif
#ifndef UXAS_ENABLE_SERIAL
#define UXAS_ENABLE_SERIAL 1
#endif

#endif
