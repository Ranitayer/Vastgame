# Keep every NVIDIA family, including workstation/datacenter models.
# Older responses may omit gpu_arch; recognize their NVIDIA model names.
# Shared hardware checks for ranking and selected-offer validation.
def compatibility_error:
    if (.vms_enabled // false) != true then {code: "VM_UNSUPPORTED", message: "This offer does not support virtual machines"}
    elif (.cpu_cores_effective | type) != "number" then {code: "CPU_UNKNOWN", message: "Provider did not report valid CPU capacity"}
    elif (.cpu_cores_effective // 0) < 4 then {code: "CPU_INSUFFICIENT", message: "CPU insufficient: needs 4 vCPUs; rig has \(.cpu_cores_effective)", required: 4, available: (.cpu_cores_effective // 0)}
    elif (.gpu_ram | type) != "number" then {code: "VRAM_UNKNOWN", message: "Provider did not report valid VRAM capacity"}
    elif (.gpu_ram // 0) < 6144 then {code: "VRAM_INSUFFICIENT", message: "VRAM insufficient: needs 6 GiB; rig has \(.gpu_ram / 1024) GiB", required: 6144, available: (.gpu_ram // 0)}
    elif (if (.gpu_arch // "") != "" then (.gpu_arch | ascii_downcase) != "nvidia"
          else ((.gpu_name // "") | test("NVIDIA|GeForce|RTX|GTX|Quadro|Tesla|Titan|^[ABHKLPTV][0-9]+([ _-]|$)"; "i") | not) end)
    then {code: "GPU_UNSUPPORTED", message: "This GPU is not supported by the Vastgame NVIDIA runtime"}
    else null end;
