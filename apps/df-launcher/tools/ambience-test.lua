-- Run with Lua 5.3+; mocks DFHack and never connects to a game or desktop.
local source, path = ...
local old_getenv = os.getenv
os.getenv = function(key) if key == 'DF_AMBIENCE_STATE' then return path end return old_getenv(key) end
local loaded, focus, timers = true, 'dwarfmode/Default', {}
SC_MAP_LOADED, SC_MAP_UNLOADED = 1, 2
local view = {getCenter=function() return {x=50,y=50,z=10} end,
    isVisible=function(_,pos) return pos.x >= 20 and pos.x <= 80 end}
package.preload['gui.dwarfmode'] = function() return {Viewport={get=function() return view end}} end
df = {game_mode={DWARF=0}, global={gamemode=0,world={units={active={}},buildings={other={TRADE_DEPOT={}}}}}}
dfhack = {isMapLoaded=function() return loaded end, onStateChange={},
    gui={getCurFocus=function() return focus end},
    units={isAlive=function(u) return not u.dead end, isCitizen=function(u) return u.citizen end,
        isResident=function(u) return u.resident end, isMerchant=function(u) return u.merchant end},
    maps={getTileFlags=function(pos) return {hidden=pos.hidden} end},
    timeout=function(_,kind,fn) assert(kind=='frames'); timers[#timers+1]=fn end,
    printerr=function(err) error(err) end}
local function unit(fields)
    local u={pos={x=50,y=50,z=10},flags1={},citizen=true}
    for k,v in pairs(fields or {}) do u[k]=v end
    return u
end
local function population(n)
    local a={}; for i=1,n do a[i]=unit() end;df.global.world.units.active=a
end
local function expect(crowd,depot)
    local f=assert(io.open(path));local s=f:read('*a');f:close()
    assert(s:match('^%d+ '..crowd..' '..depot..'\n$'),s)
end
local function tick()
    local old=timers;timers={};for _,fn in ipairs(old) do fn() end
    assert(#timers <= 1,'duplicate polling loop')
end
population(2);dofile(source);expect(0,0)
for _,case in ipairs{{3,1},{7,1},{8,2},{19,2},{20,3}} do
    population(case[1]);tick();expect(case[2],0)
end
-- Dead, hidden, caged, distant and other-level units must not swell crowds.
df.global.world.units.active={unit(),unit(),unit{dead=true},unit{flags1={caged=true}},
    unit{pos={x=50,y=50,z=9}},unit{pos={x=50,y=50,z=10,hidden=true}},
    unit{pos={x=70,y=50,z=10}},unit{citizen=false}}
tick();expect(0,0)
local merchant=unit{citizen=false,merchant=true}
df.global.world.units.active={merchant}
local depot={z=10,x1=48,x2=52,y1=48,y2=52,
    getBuildStage=function() return 3 end,getMaxBuildStage=function() return 3 end}
df.global.world.buildings.other.TRADE_DEPOT={depot}
tick();expect(0,1)
depot.getBuildStage=function() return 1 end;tick();expect(0,0)
depot.getBuildStage=function() return 3 end
merchant.pos.x=60;tick();expect(0,0)
merchant.pos.x=50;focus='title';tick();expect(0,0)
focus='dwarfmode/Default';tick();expect(0,1)
loaded=false;dfhack.onStateChange.df_launcher_ambience(SC_MAP_UNLOADED);expect(0,0)
loaded=true;dfhack.onStateChange.df_launcher_ambience(SC_MAP_LOADED);tick();expect(0,1)
loaded=false;dfhack.onStateChange.df_launcher_ambience(SC_MAP_UNLOADED);tick();expect(0,0)
assert(#timers==0)
print('activity thresholds, visibility, depot presence and map lifecycle passed')
