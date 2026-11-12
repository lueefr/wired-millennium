local millennium = require('millennium')
local json = require('json')
local logger = require('logger')
local utils = require('utils')
local backend = MILLENNIUM_PLUGIN_SECRET_BACKEND_ABSOLUTE
local service = backend .. '/service.py'
local stat = assert(io.open('/proc/self/stat', 'r'))
local pid = stat:read('*l'):match('^(%d+)')
stat:close()
local directory = (os.getenv('HOME') or error('HOME unavailable')) .. '/.local/share/wired-millennium/ipc/wired-' .. pid
local sequence = 0
local running = false

local function quote(value)
    return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end
local python = '/usr/bin/env -u LD_PRELOAD -u LD_AUDIT -u LD_LIBRARY_PATH -u PYTHONPATH -u PYTHONHOME /usr/bin/python3 '
local _, launch_code = utils.exec('test -x /usr/bin/steam-runtime-launch-client')
if launch_code == 0 then
    python = '/usr/bin/steam-runtime-launch-client --alongside-steam -- ' .. python
end
local function forward(payload)
    sequence = sequence + 1
    local path = directory .. '/request-' .. sequence .. '.json'
    local file, err = io.open(path, 'w')
    if not file then return json.encode({success=false, error=tostring(err)}) end
    file:write(payload)
    file:close()
    local output = utils.exec(python .. quote(service) .. ' client ' .. quote(directory) .. ' --request ' .. quote(path))
    if not output or output == '' then
        logger:error('Wired: internal service unresponsive')
        return json.encode({success=false, error='Internal service unresponsive'})
    end
    local decoded, result = pcall(json.decode, output)
    if decoded and type(result) == 'table' then
        for _, event in ipairs(result._wired_logs or {}) do
            if event.level == 'error' then logger:error(event.message)
            elseif event.level == 'warning' or event.level == 'warn' then logger:warn(event.message)
            else logger:info(event.message) end
        end
        return output
    end
    logger:error('Wired: Invalid response from internal service')
    return output
end

-- One JSON argument avoids depending on keyword iteration order in Lua RPC.
function WiredRPC(payload_json)
    local ok, payload = pcall(json.decode, payload_json)
    if ok and payload.method == 'OpenFixes' then
        local appid = tonumber(payload.args and payload.args.appid)
        if not appid or appid < 1 or appid >= 4294967296 or appid ~= math.floor(appid) then
            return json.encode({success=false,error='Invalid AppID'})
        end
        local raw = forward(json.encode({method='GetIntegrationState',args={appids_json=json.encode({appid})}}))
        local parsed, state = pcall(json.decode, raw)
        local app = parsed and state.apps and state.apps[tostring(appid)]
        if not app or not app.added or not app.installed then
            return json.encode({success=false,error='Add and install the game before opening Fixes'})
        end
        local result, err = millennium.call_frontend_method('OpenFixes', {appid})
        if not result then return json.encode({success=false,error=tostring(err or 'Native interface unavailable')}) end
        return json.encode({success=true})
    end
    return forward(payload_json)
end

local function on_load()
    local _, code = utils.exec('mkdir -p ' .. quote(directory) .. ' && chmod 700 ' .. quote(directory))
    if code ~= 0 then error('Unable to create Wired IPC directory') end
    utils.exec(python .. quote(service) .. ' serve ' .. quote(directory) .. ' --parent ' .. pid .. ' > ' .. quote(directory .. '/service.log') .. ' 2>&1 < /dev/null &')
    local output = utils.exec(python .. quote(service) .. ' ping ' .. quote(directory))
    local ok, result = pcall(json.decode, output or '')
    if not ok or not result.success then error('Wired: engine startup failure:' .. tostring(output)) end
    running = true
    millennium.ready()
    logger:info('Wired 0.7.0: Lua backend and internal engine ready')
end
local function on_unload()
    if running then
        pcall(forward, json.encode({method='Shutdown', args={}}))
        running = false
    end
end
local function on_frontend_loaded()
    logger:info('Wired frontend connected')
    local result, err = millennium.call_frontend_method('RuntimeProbe', {})
    if result then logger:info('Wired UI probe: ' .. tostring(result))
    else logger:warn('Wired UI probe unavailable:' .. tostring(err)) end
end
return {on_load=on_load, on_unload=on_unload, on_frontend_loaded=on_frontend_loaded}
