-- Owned by Dwarf Fortress Launcher. Supplies fortress activity to ambience.so.
local path = os.getenv('DF_AMBIENCE_STATE')
if not path or os.getenv('DF_AMBIENCE_FIX') == '0' then return end
local guidm = require('gui.dwarfmode')
generation = (generation or 0) + 1
local current_generation = generation
local map_generation = 0

local function publish(crowd, depot)
    local file = assert(io.open(path .. '.new', 'w'))
    file:write(('%d %d %d\n'):format(os.time(), crowd, depot and 1 or 0))
    assert(file:close())
    assert(os.rename(path .. '.new', path))
end

local function observe()
    if not dfhack.isMapLoaded() or df.global.gamemode ~= df.game_mode.DWARF or
        not dfhack.gui.getCurFocus():match('^dwarfmode') then return 0, false end
    local view = guidm.Viewport.get()
    local center = view:getCenter()
    local people, merchants = 0, {}
    for _, unit in ipairs(df.global.world.units.active) do
        local pos = unit.pos
        if pos.z == center.z and view:isVisible(pos) and
            math.abs(pos.x - center.x) <= 16 and math.abs(pos.y - center.y) <= 16 and
            dfhack.units.isAlive(unit) and not unit.flags1.caged and
            (dfhack.units.isCitizen(unit) or dfhack.units.isResident(unit) or
             dfhack.units.isMerchant(unit)) then
            local flags = dfhack.maps.getTileFlags(pos)
            if flags and not flags.hidden then
                people = people + 1
                if dfhack.units.isMerchant(unit) then merchants[#merchants + 1] = pos end
            end
        end
    end
    local depot = false
    for _, building in ipairs(df.global.world.buildings.other.TRADE_DEPOT) do
        if building.z == center.z and
            building:getBuildStage() == building:getMaxBuildStage() then
            for _, pos in ipairs(merchants) do
                if pos.x >= building.x1 - 2 and pos.x <= building.x2 + 2 and
                    pos.y >= building.y1 - 2 and pos.y <= building.y2 + 2 then
                    depot = true
                    break
                end
            end
        end
        if depot then break end
    end
    return people >= 20 and 3 or people >= 8 and 2 or people >= 3 and 1 or 0, depot
end

local function poll(token)
    if generation ~= current_generation or token ~= map_generation then return end
    local ok, err = pcall(function() publish(observe()) end)
    if not ok then
        dfhack.printerr('df-ambience: activity observation stopped: ' .. tostring(err))
        return -- The native reader expires stale observations and fades out.
    end
    if dfhack.isMapLoaded() then dfhack.timeout(10, 'frames', function() poll(token) end) end
end

dfhack.onStateChange.df_launcher_ambience = function(code)
    if code == SC_MAP_LOADED then
        map_generation = map_generation + 1
        poll(map_generation)
    elseif code == SC_MAP_UNLOADED then
        map_generation = map_generation + 1
        publish(0, false)
    end
end
if dfhack.isMapLoaded() then poll(map_generation) else publish(0, false) end
