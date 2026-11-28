/* Link only into the isolated ambience harness, never into the game. */
#include <string.h>
int counts[4], starts[4];
float walla = .5f;
int FMOD_Studio_System_GetEvent(void *s, const char *path, void **out)
{
    (void)s;
    int i = strstr(path,"Tavern") ? 0 : strstr(path,"Workshop") ? 1 : strstr(path,"TradeDepot") ? 2 : 3;
    *out = &counts[i]; return 0;
}
int FMOD_Studio_EventDescription_GetInstanceCount(void *d, int *n) { *n=*(int *)d; return 0; }
int FMOD_Studio_EventDescription_CreateInstance(void *d, void **out) { ++*(int *)d; *out=d; return 0; }
int FMOD_Studio_EventInstance_Start(void *i) { ++starts[(int *)i-counts]; return 0; }
int FMOD_Studio_EventInstance_Stop(void *i,int mode) { (void)i;(void)mode;return 0; }
int FMOD_Studio_EventInstance_Release(void *i) { --*(int *)i;return 0; }
int FMOD_Studio_EventInstance_SetVolume(void *i,float v) { (void)i;(void)v;return 0; }
int FMOD_Studio_System_SetParameterByName(void *s,const char *n,float v,int ignore)
{ (void)s;(void)n;(void)ignore;walla=v;return 0; }
int FMOD_Studio_System_GetParameterByName(void *s,const char *n,float *v,float *final)
{ (void)s;(void)n;(void)final;*v=walla;return 0; }
int native_update(void *s) __asm__("_ZN4FMOD6Studio6System6updateEv");
int native_update(void *s) { (void)s;return 0; }
int native_unload(void *s) __asm__("_ZN4FMOD6Studio6System9unloadAllEv");
int native_unload(void *s) { (void)s;return 0; }
