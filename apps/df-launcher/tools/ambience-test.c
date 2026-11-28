/* Build with ambience-mock.c as a separate shared library; uses no FMOD/device. */
#include "../ambience.c"
#include <assert.h>
extern int counts[4], starts[4];
extern float walla;
static time_t clock_now=1700000000;
time_t time(time_t *out) { if(out)*out=clock_now;return clock_now; }
static void observation(int crowd,int depot,int age)
{
    ++clock_now;
    FILE *f=fopen(activity_path,"w");assert(f);
    fprintf(f,"%lld %d %d\n",(long long)clock_now-age,crowd,depot);fclose(f);
}
static void frames(void) { for(int i=0;i<300;++i) assert(update(NULL)==0); }
int main(int argc,char **argv)
{
    assert(argc==2);assert(!enabled);enabled=true;activity_path=argv[1];
    observation(3,1,0);atomic_store(&surroundings,6);frames();
    assert(starts[0]==1 && starts[1]==1 && starts[2]==1 && starts[3]==0);
    observation(3,0,0);atomic_store(&surroundings,0);frames();
    assert(counts[0]==0 && counts[1]==0 && counts[2]==0 && counts[3]==1 && walla==3);
    observation(1,0,0);frames();assert(starts[3]==1 && walla==1);
    observation(3,1,6);frames();assert(counts[2]==0 && counts[3]==0 && walla==.5f);
    observation(99,1,0);frames();assert(counts[2]==0 && counts[3]==0);
    observation(3,0,0);frames();assert(counts[3]==1);
    assert(unload(NULL)==0);assert(counts[3]==0 && walla==.5f);
    observation(0,0,0);counts[0]=1;atomic_store(&surroundings,2);frames();
    assert(starts[0]==1 && counts[0]==1); /* Leave an existing native event alone. */
    puts("fades, density changes, expiry, malformed state, unloading and duplicate suppression passed");
}
