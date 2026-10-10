include "eligibility";
# --------------------------------------------------------
    # Absolute GPU gaming score: 0..40
    #
    # Model ordering is tuned for modern 1440p/1600p gaming.
    # total_flops is ONLY a fallback for an unknown future GPU.
    # --------------------------------------------------------

    def gpu_pts:

        ((.gpu_name // "")
            | ascii_upcase
            | gsub("[_-]"; " ")
        ) as $g

        |

        if   ($g | test("RTX 5090")) then 40.0
        elif ($g | test("RTX 4090")) then 39.0
        elif ($g | test("RTX 5080")) then 37.0

        elif ($g | test("RTX 4080 ?(SUPER|S)")) then 35.0
        elif ($g | test("RTX 4080")) then 34.5

        elif ($g | test("RTX 5070 TI")) then 34.0
        elif ($g | test("RTX 4070 TI ?(SUPER|S)")) then 31.0

        elif ($g | test("RTX 3090 TI")) then 30.0
        elif ($g | test("RTX 4070 TI")) then 29.5
        elif ($g | test("RTX 5070")) then 29.0

        elif ($g | test("RTX 3090")) then 28.0
        elif ($g | test("RTX 4070 ?(SUPER|S)")) then 28.0
        elif ($g | test("RTX 3080 TI")) then 27.5

        elif ($g | test("RTX 3080")) then 25.5
        elif ($g | test("RTX 4070")) then 24.5

        elif ($g | test("RTX 5060 TI")) then 23.0
        elif ($g | test("RTX 3070 TI")) then 21.5
        elif ($g | test("RTX 5060")) then 20.5
        elif ($g | test("RTX 4060 TI")) then 20.5
        elif ($g | test("RTX 3070")) then 20.0

        elif ($g | test("RTX 3060 TI")) then 18.0
        elif ($g | test("RTX 4060")) then 17.0
        elif ($g | test("RTX 3060")) then 15.0

        elif ($g | test("RTX 2080 TI")) then 14.5
        elif ($g | test("RTX 2080 ?(SUPER|S)")) then 12.5
        elif ($g | test("RTX 2080")) then 11.5
        elif ($g | test("RTX 2070 ?(SUPER|S)")) then 10.5
        elif ($g | test("RTX 2070")) then 9.5
        elif ($g | test("RTX 2060")) then 8.0

        else
            (
                (.total_flops // 0) * 0.55
            ) as $fallback
            |
            if $fallback < 6 then 6
            elif $fallback > 24 then 24
            else $fallback
            end
        end
    ;

    # Country points are geographic estimates from bundled public-domain locations.
    def preferences: ($ARGS.named.host_preferences // {});
    def proximity_pts:
        ((.geolocation // "") | ascii_upcase | capture("(?<code>[A-Z]{2})$")?.code // "") as $code |
        (preferences.country_points[$code] // 6)
    ;
    def preferred_gpu_pts:
        (preferences.preferred_gpu // "" | ascii_upcase | gsub("[_-]"; " ")) as $preferred |
        if $preferred != "" and ((.gpu_name // "") | ascii_upcase | gsub("[_-]"; " ")) == $preferred
        then 5 else 0 end
    ;
    def matches_preferences:
        preferences as $p |
        (($p.verified_only // false) == false or .verified == true or (.verification // "" | tostring | ascii_downcase) == "verified") and
        ((.inet_down // 0) >= ($p.min_download_mbps // 0)) and
        ((.inet_up // 0) >= ($p.min_upload_mbps // 0)) and
        ((.gpu_ram // 0) >= (($p.min_vram_gb // 0) * 1024)) and
        ((.cpu_ram // 0) >= (($p.min_ram_gb // 0) * 1024))
    ;

    # --------------------------------------------------------
    # Network/storage: 0..12. Keep the total score scale unchanged.
    def restore_rate($h):
        ($h["machine:" + ((.machine_id // "") | tostring)] // {}) as $x |
        if ($x.restore_mbps // 0) > 0 and (now - ($x.last_restore // 0)) < 604800
        then $x.restore_mbps
        else (.inet_down // 0)
        end
    ;

    def net_pts($h):
        (if (.inet_up // 0) >= 500 then 4
         elif (.inet_up // 0) >= 150 then 3.5
         elif (.inet_up // 0) >= 75 then 3 else 2 end)
        +
        (restore_rate($h) as $down |
         if $down >= 5000 then 6
         elif $down >= 2500 then 5.5
         elif $down >= 1000 then 4.5
         elif $down >= 500 then 3
         elif $down >= 250 then 1.8 else 0.6 end)
        +
        (if (.disk_bw // 0) >= 1000 then 2
         elif (.disk_bw // 0) >= 500 then 1.5
         elif (.disk_bw // 0) >= 250 then 1
         elif (.disk_bw // 0) > 0 then 0.5 else 0 end)
    ;

    # --------------------------------------------------------
    # Reliability: 0..12, intentionally nonlinear.
    # --------------------------------------------------------

    def rel_pts:

        if   (.reliability // 0) >= 0.999 then 12.0
        elif (.reliability // 0) >= 0.995 then 11.5
        elif (.reliability // 0) >= 0.990 then 10.5
        elif (.reliability // 0) >= 0.985 then 9.5
        elif (.reliability // 0) >= 0.980 then 8.5
        elif (.reliability // 0) >= 0.970 then 7.0
        elif (.reliability // 0) >= 0.950 then 5.0
        else 1.0
        end
    ;

    # --------------------------------------------------------
    # VRAM: 0..8
    # --------------------------------------------------------

    def vram_pts:

        ((.gpu_ram // 0) / 1024) as $v

        |

        if   $v >= 24 then 8.0
        elif $v >= 16 then 7.5
        elif $v >= 12 then 6.5
        elif $v >= 10 then 5.5
        elif $v >= 8  then 4.5
        elif $v >= 6  then 2.5
        else 1.0
        end
    ;

    # --------------------------------------------------------
    # CPU/server: 0..6
    # --------------------------------------------------------

    def cpu_pts:

        (
            if   (.cpu_cores_effective // 0) >= 16 then 4.0
            elif (.cpu_cores_effective // 0) >= 12 then 3.6
            elif (.cpu_cores_effective // 0) >= 8  then 3.1
            elif (.cpu_cores_effective // 0) >= 6  then 2.6
            elif (.cpu_cores_effective // 0) >= 4  then 2.0
            else 0.5
            end
        )

        +

        (
            if   (.cpu_ghz // 0) >= 3.5 then 2.0
            elif (.cpu_ghz // 0) >= 3.0 then 1.7
            elif (.cpu_ghz // 0) >= 2.5 then 1.3
            elif (.cpu_ghz // 0) >= 2.0 then 0.9
            else 0.4
            end
        )
    ;

    # --------------------------------------------------------
    # Price/value: 0..20. Extra GPU power stops earning points at the target.
    def cost_pts:
        (1 - ((.dph_total // $cap) / ($ARGS.named.value_cap // $cap))) * 20 | [0, .] | max
    ;

    # Hardware is an estimate, not a promised FPS. Matching game samples win.
    def game_fit($h):
        ($h["machine:" + ((.machine_id // "") | tostring)] // {}) as $x |
        ([$x.performance_sessions[]?, $x.performance?]
         | map(select(. != null and (.samples // 0) >= 30
             and (.updated // 0) >= (now - 604800)
             and .game_id == $selected_game and .resolution == $native_resolution
             and .target_fps == $native_fps and (.game_fps // 0) > 0))
         | sort_by(.updated) | last) as $sample |
        if $sample != null then
            {fit: ([1, ($sample.game_fps / $native_fps)] | min), basis: "Game measured"}
        else
            ($native_resolution | split("x") | map(tonumber?)) as $size |
            (((($size[0] // 1920) * ($size[1] // 1080) / 2073600) | sqrt)
              * (($native_fps / 60) | sqrt) * 24 | [18, .] | max | [40, .] | min) as $needed |
            {fit: ([1, (gpu_pts / $needed)] | min), basis: "Estimated"}
        end
    ;

    # --------------------------------------------------------
    # Learned history: recent provider failures -30..-18
    # machine_id is preferred over country guesses.
    # --------------------------------------------------------

    def hist_bonus($h):

        ("machine:" + ((.machine_id // "") | tostring)) as $key
        |
        ($h[$key] // {}) as $x

        |

        ([$x.provisioning_failures[]? | select(.category == "provider_gpu" and (now - .time) < 604800)] | length) as $boot_failures |
        if $boot_failures >= 2 then -30
        elif $boot_failures == 1 then -18
        else 0
        end
    ;

    def performance_bonus($h):
        ($h["machine:" + ((.machine_id // "") | tostring)].performance // {}) as $p
        | if ($p.samples // 0) < 30 or ($p.updated // 0) < (now - 604800) then 0
          else
            (if ($p.delivery_score // 0) >= 95 then 4
             elif ($p.delivery_score // 0) >= 80 then 2
             elif ($p.delivery_score // 100) < 40 then -8
             elif ($p.delivery_score // 100) < 65 then -4 else 0 end)
            +
            (if $p.game_id != $selected_game or $p.resolution != $native_resolution or $p.target_fps != $native_fps then 0
             elif ($p.game_delivery_score // 0) >= 95 then 2
             elif ($p.game_delivery_score // 100) < 60 then -4 else 0 end)
          end
    ;

    def tier($s):
        if   $s >= 93 then "S+"
        elif $s >= 87 then "S"
        elif $s >= 80 then "A"
        elif $s >= 72 then "B"
        elif $s >= 64 then "C"
        else "D"
        end
    ;

    def r1:
        ((. * 10) | round) / 10
    ;

    ($hist[0] // {}) as $history

    |

    map(select((.dph_total // 999) <= $cap and compatibility_error == null and matches_preferences))

    |

    map(
        game_fit($history) as $game
        |
        ($game.fit * 35) as $gpu
        |
        proximity_pts as $proximity
        |
        preferred_gpu_pts as $preferred
        |
        (net_pts($history) * 10 / 12) as $net
        |
        (rel_pts * 10 / 12) as $rel
        |
        (vram_pts * 5 / 8) as $vram
        |
        (cpu_pts * 5 / 6) as $cpu
        |
        (cost_pts * $game.fit) as $cost
        |
        (hist_bonus($history) + performance_bonus($history)) as $hist

        |

        (
            $gpu
            + $proximity
            + $preferred
            + $net
            + $rel
            + $vram
            + $cpu
            + $cost
            + $hist
        ) as $raw

        |

        (
            if $raw > 100 then 100
            elif $raw < 0 then 0
            else $raw
            end
        ) as $score

        |

        . + {
            _vg: {
                score: ($score | r1),
                target_resolution: $native_resolution,
                target_fps: $native_fps,
                basis: $game.basis,
                tier: tier($score),

                gpu: ($gpu | r1),
                proximity: ($proximity | r1),
                preference: $preferred,
                net: ($net | r1),
                restore_mbps: restore_rate($history),
                rel: ($rel | r1),
                vram: ($vram | r1),
                cpu: ($cpu | r1),
                cost: ($cost | r1),
                hist: ($hist | r1)
            }
        }
    )

    |

    sort_by(
        [
            -._vg.score,
            (.dph_total // 999),
            -._vg.gpu,
            -._vg.proximity,
            -._vg.rel,
            -._vg.restore_mbps,
            -(.disk_bw // 0),
            -(.inet_up // 0),
            (.dph_total // 999)
        ]
    )

    |

    .[:$max]
