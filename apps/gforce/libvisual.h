/* Standalone equivalents of the three Libvisual utilities used by the core. */
#pragma once
#include <sys/time.h>
#include <string.h>
#include <stdio.h>
typedef struct timeval VisTime;
#define visual_time_get(t) gettimeofday((t), NULL)
#define visual_mem_set memset
#define VISUAL_LOG_WARNING 0
#define visual_log(level, ...) do { fprintf(stderr, __VA_ARGS__); fputc('\n', stderr); } while (0)
