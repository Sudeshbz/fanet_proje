#!/usr/bin/env python3
"""
FANET Canlı Topoloji Görselleştirici
Mininet çalışırken ayrı pencerede canlı güncellenir.
"""
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.animation as animation
import networkx as nx
import json, os, time, math, random
import threading

# UAV/UGV pozisyonları (Mininet ile aynı)
NODE_POS = {
    "uav1": (100, 200), "uav2": (250, 300),
    "uav3": (400, 150), "uav4": (500, 350),
    "uav5": (150, 450), "ugv1": (50,  50),
    "ugv2": (550, 500),
}
RANGE = {"uav": 200, "ugv": 300}
COLORS = {"uav": "#FF9800", "ugv": "#607D8B", "head": "#E31E24", "link": "#90CAF9"}

# Simüle mobilite
positions = {k: list(v) for k, v in NODE_POS.items()}
energies  = {k: 100.0 for k in NODE_POS}
cluster_heads = ["uav1", "ugv1", "ugv2"]

def distance(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)

def get_links():
    links = []
    nodes = list(positions.keys())
    for i in range(len(nodes)):
        for j in range(i+1, len(nodes)):
            n1, n2 = nodes[i], nodes[j]
            r = RANGE["ugv"] if "ugv" in n1 or "ugv" in n2 else RANGE["uav"]
            if distance(positions[n1], positions[n2]) < r:
                links.append((n1, n2))
    return links

def move_uavs():
    """UAV'ları hareket ettir."""
    while True:
        for name in [k for k in positions if "uav" in k]:
            positions[name][0] += random.uniform(-8, 8)
            positions[name][1] += random.uniform(-8, 8)
            positions[name][0]  = max(20, min(580, positions[name][0]))
            positions[name][1]  = max(20, min(580, positions[name][1]))
            energies[name] = max(10, energies[name] - random.uniform(0.1, 0.3))
        time.sleep(1)

# Arka planda mobilite başlat
t = threading.Thread(target=move_uavs, daemon=True)
t.start()

# ── Görselleştirme ────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(16, 8))
fig.patch.set_facecolor("#1a1a2e")
fig.suptitle("FANET LB-MCR — Canlı Topoloji İzleme\nTÜBİTAK 2209-A | Sude Filikci",
             color="white", fontsize=13, fontweight="bold")

def animate(frame):
    for ax in axes:
        ax.cla()
        ax.set_facecolor("#16213e")

    links = get_links()

    # ── Sol: Topoloji haritası ────────────────────────────
    ax = axes[0]
    ax.set_xlim(0, 600); ax.set_ylim(0, 600)
    ax.set_title("Ağ Topolojisi & Kapsama Alanları",
                 color="white", fontsize=11)
    ax.tick_params(colors="gray")
    ax.set_xlabel("X (metre)", color="gray")
    ax.set_ylabel("Y (metre)", color="gray")
    for spine in ax.spines.values():
        spine.set_edgecolor("#333")

    # Kapsama alanları
    for name, pos in positions.items():
        r     = RANGE["ugv"] if "ugv" in name else RANGE["uav"]
        color = "#607D8B" if "ugv" in name else "#FF9800"
        circle = plt.Circle(pos, r, color=color, alpha=0.06, linewidth=1,
                             linestyle="--", fill=True)
        ax.add_patch(circle)
        circle2 = plt.Circle(pos, r, color=color, alpha=0.3, linewidth=1,
                              linestyle="--", fill=False)
        ax.add_patch(circle2)

    # Linkler
    for n1, n2 in links:
        p1, p2 = positions[n1], positions[n2]
        # Küme başları arası link farklı renk
        if n1 in cluster_heads and n2 in cluster_heads:
            ax.plot([p1[0],p2[0]], [p1[1],p2[1]],
                    color="#E31E24", linewidth=2, alpha=0.8, zorder=1)
        else:
            ax.plot([p1[0],p2[0]], [p1[1],p2[1]],
                    color=COLORS["link"], linewidth=1, alpha=0.5, zorder=1)

    # Düğümler
    for name, pos in positions.items():
        is_ugv  = "ugv" in name
        is_head = name in cluster_heads
        color   = COLORS["head"] if is_head else (COLORS["ugv"] if is_ugv else COLORS["uav"])
        marker  = "s" if is_ugv else "^"
        size    = 200 if is_ugv else 150
        ax.scatter(pos[0], pos[1], c=color, s=size,
                   marker=marker, zorder=5, edgecolors="white", linewidth=1.5)
        # İsim etiketi
        ax.annotate(name.upper(),
                    xy=pos, xytext=(pos[0]+8, pos[1]+8),
                    color="white", fontsize=8, fontweight="bold")
        # Enerji göstergesi (UAV için)
        if not is_ugv:
            e = energies[name]
            e_color = "#4CAF50" if e > 50 else "#FF9800" if e > 25 else "#F44336"
            ax.annotate(f"{e:.0f}%",
                        xy=pos, xytext=(pos[0]+8, pos[1]-12),
                        color=e_color, fontsize=7)

    # Legend
    legend_elements = [
        mpatches.Patch(color=COLORS["uav"],  label="UAV"),
        mpatches.Patch(color=COLORS["ugv"],  label="UGV"),
        mpatches.Patch(color=COLORS["head"], label="Küme Başı"),
        mpatches.Patch(color=COLORS["link"], label="Link"),
        mpatches.Patch(color="#E31E24",      label="Küme Başı Linki"),
    ]
    ax.legend(handles=legend_elements, loc="upper right",
              facecolor="#1a1a2e", labelcolor="white", fontsize=8)
    ax.grid(alpha=0.1, color="gray")

    # ── Sağ: Anlık metrikler ──────────────────────────────
    ax = axes[1]
    ax.set_xlim(0, 10); ax.set_ylim(0, 10)
    ax.set_title("Anlık Ağ Metrikleri", color="white", fontsize=11)
    ax.axis("off")

    n_links   = len(links)
    n_nodes   = len(positions)
    avg_energy= sum(energies[k] for k in energies if "uav" in k) / 5
    low_energy= [k for k in energies if "uav" in k and energies[k] < 30]

    metrics = [
        ("Aktif Düğüm",    f"{n_nodes}",           "#4CAF50"),
        ("Aktif Link",     f"{n_links}",            "#2196F3"),
        ("Küme Sayısı",    f"{len(cluster_heads)}", "#E31E24"),
        ("Ort. Enerji",    f"{avg_energy:.1f}%",    "#FF9800" if avg_energy<50 else "#4CAF50"),
        ("Kritik Düğüm",  f"{len(low_energy)}",    "#F44336" if low_energy else "#4CAF50"),
        ("Protokol",       "LB-MCR",                "#E31E24"),
        ("Kontrolcü",      "Ryu SDN",               "#9C27B0"),
        ("Platform",       "Mininet-WiFi",           "#00BCD4"),
    ]

    for i, (label, value, color) in enumerate(metrics):
        y = 9.2 - i * 1.1
        ax.text(0.5, y, label, color="gray",   fontsize=10, va="center")
        ax.text(6.0, y, value, color=color,    fontsize=11, va="center", fontweight="bold")
        ax.axhline(y=y-0.4, color="#333", linewidth=0.5, alpha=0.5)

    # Zaman damgası
    ax.text(5, 0.3, f"t = {frame*1:.0f}s",
            color="gray", fontsize=9, ha="center")

    # Ryu log son satırı
    try:
        with open("/tmp/ryu.log") as f:
            lines = f.readlines()
            last = [l.strip() for l in lines[-3:] if l.strip()]
        for i, line in enumerate(last):
            ax.text(0.3, 1.8-i*0.5, line[-60:], color="#666",
                    fontsize=7, va="center")
    except:
        ax.text(0.3, 1.5, "Ryu log bekleniyor...",
                color="#666", fontsize=8)

    plt.tight_layout(rect=[0, 0, 1, 0.93])

ani = animation.FuncAnimation(fig, animate, interval=1000, cache_frame_data=False)
plt.show()
