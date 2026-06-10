#!/usr/bin/env python3
"""
LB-MCR: Load-Balanced Multipath Cluster-based Routing Controller
Yalova Üniversitesi - FANET SDN Projesi

Ryu SDN kontrolcüsü: UAV-UGV hibrit ağda çok yollu kümeleme tabanlı
yönlendirme + coğrafi açgözlü onarım (greedy repair) mekanizması.
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, arp
from ryu.lib import hub
import networkx as nx
import math
import time
import logging
import json
import csv
import os
from collections import defaultdict

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('LB_MCR')

# ─────────────────────────────────────────
# Sabitler
# ─────────────────────────────────────────
MONITOR_INTERVAL   = 2      # saniye
CLUSTER_THRESHOLD  = 3      # küme başı seçimi için min komşu sayısı
ENERGY_THRESHOLD   = 20.0   # % - kritik enerji seviyesi
LINK_TIMEOUT       = 10     # saniye - link ömrü
MAX_PATHS          = 3      # çok yollu maks rota sayısı
GREEDY_RADIUS      = 150.0  # metre - greedy onarım yarıçapı
RESULTS_DIR        = "/tmp/fanet_results"


# ─────────────────────────────────────────
# Düğüm Bilgi Sınıfı
# ─────────────────────────────────────────
class FANETNode:
    """UAV veya UGV düğümünü temsil eder."""

    def __init__(self, node_id, node_type="UAV", x=0.0, y=0.0, z=0.0):
        self.node_id   = node_id
        self.node_type = node_type   # "UAV" | "UGV"
        self.x = x
        self.y = y
        self.z = z
        self.energy    = 100.0       # %
        self.load      = 0.0         # 0-1 normalize
        self.is_cluster_head = False
        self.cluster_id      = None
        self.last_seen       = time.time()
        self.tx_bytes        = 0
        self.rx_bytes        = 0

    def distance_to(self, other):
        return math.sqrt(
            (self.x - other.x)**2 +
            (self.y - other.y)**2 +
            (self.z - other.z)**2
        )

    def update_energy(self, tx_bytes, dt):
        """Basit enerji tüketim modeli (mJ)."""
        E_TX = 50e-9   # J/bit iletim
        E_RX = 50e-9
        bits = tx_bytes * 8
        consumed = (E_TX * bits) * 100 / 10000  # normalize %
        self.energy = max(0.0, self.energy - consumed * dt)

    def to_dict(self):
        return {
            "id":           self.node_id,
            "type":         self.node_type,
            "x":            self.x,
            "y":            self.y,
            "z":            self.z,
            "energy":       self.energy,
            "load":         self.load,
            "cluster_head": self.is_cluster_head,
            "cluster_id":   self.cluster_id,
        }


# ─────────────────────────────────────────
# Ana Kontrolcü
# ─────────────────────────────────────────
class LBMCRController(app_manager.RyuApp):
    """
    SDN Kontrolcüsü: LB-MCR algoritması.

    Görevler:
    1. Ağ topolojisini izle (LLDP/port stats).
    2. Kümeleme yap (enerji + yük + bağlantı süresi).
    3. Çok yollu rotalar hesapla.
    4. Bağlantı kopması → greedy onarım.
    5. Performans metrikleri kaydet.
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Veri yapıları
        self.topology      = nx.Graph()          # ağ topoloji grafiği
        self.nodes         = {}                  # node_id → FANETNode
        self.datapaths     = {}                  # dpid → datapath
        self.mac_to_port   = defaultdict(dict)   # dpid → {mac: port}
        self.flow_paths    = {}                  # (src,dst) → [path1, path2, ...]
        self.clusters      = {}                  # cluster_id → {head, members}
        self.link_stats    = {}                  # (dpid1,dpid2) → stats

        # Metrik kayıt
        os.makedirs(RESULTS_DIR, exist_ok=True)
        self.metrics_file = open(f"{RESULTS_DIR}/metrics.csv", "w", newline="")
        self.metrics_writer = csv.writer(self.metrics_file)
        self.metrics_writer.writerow([
            "timestamp", "event", "src", "dst",
            "throughput_mbps", "delay_ms", "packet_loss",
            "energy_avg", "active_paths"
        ])

        # Demo düğümler yükle (Mininet bağlanınca gerçek değerlerle güncellenir)
        self._init_demo_nodes()

        # Arka plan izleme döngüsü
        self.monitor_thread = hub.spawn(self._monitor_loop)
        logger.info("LB-MCR Kontrolcüsü başlatıldı.")

    # ── Demo topoloji ──────────────────────────────────────────────
    def _init_demo_nodes(self):
        """Test için sabit UAV/UGV konumları."""
        demo = [
            ("uav1", "UAV", 100, 200, 50),
            ("uav2", "UAV", 250, 300, 60),
            ("uav3", "UAV", 400, 150, 55),
            ("uav4", "UAV", 500, 350, 70),
            ("uav5", "UAV", 150, 450, 45),
            ("ugv1", "UGV",  50,  50,  0),
            ("ugv2", "UGV", 550, 500,  0),
        ]
        for nid, ntype, x, y, z in demo:
            self.nodes[nid] = FANETNode(nid, ntype, x, y, z)
            self.topology.add_node(nid, **self.nodes[nid].to_dict())

        # Başlangıç linkleri (mesafe < 200m)
        node_list = list(self.nodes.values())
        for i in range(len(node_list)):
            for j in range(i + 1, len(node_list)):
                n1, n2 = node_list[i], node_list[j]
                dist = n1.distance_to(n2)
                if dist < 200:
                    w = self._link_weight(n1, n2, dist)
                    self.topology.add_edge(n1.node_id, n2.node_id,
                                          weight=w, distance=dist,
                                          last_seen=time.time())
        logger.info(f"Demo topoloji: {len(self.nodes)} düğüm, "
                    f"{self.topology.number_of_edges()} link")
        self._run_clustering()

    # ── OF Olay İşleyicileri ───────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp      = ev.msg.datapath
        ofp     = dp.ofproto
        parser  = dp.ofproto_parser
        self.datapaths[dp.id] = dp

        # Table-miss: paketi kontrolcüye gönder
        match  = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER,
                                          ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, 0, match, actions)
        logger.info(f"Switch bağlandı: dpid={dp.id}")

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg    = ev.msg
        dp     = msg.datapath
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        in_port = msg.match['in_port']

        pkt  = packet.Packet(msg.data)
        eth  = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == 0x88cc:   # LLDP → topoloji güncellemesi
            return

        dst_mac = eth.dst
        src_mac = eth.src
        dpid    = dp.id

        self.mac_to_port[dpid][src_mac] = in_port

        # Çok yollu rota seçimi
        out_port = self._select_output_port(dpid, src_mac, dst_mac, in_port)

        actions = [parser.OFPActionOutput(out_port)]

        # Flow kural ekle (yüksek öncelik)
        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst_mac,
                                    eth_src=src_mac)
            if msg.buffer_id != ofp.OFP_NO_BUFFER:
                self._add_flow(dp, 1, match, actions,
                               buffer_id=msg.buffer_id)
                return
            else:
                self._add_flow(dp, 1, match, actions)

        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        out  = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id,
            in_port=in_port, actions=actions, data=data
        )
        dp.send_msg(out)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        """Port istatistiklerinden throughput hesapla."""
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        for stat in body:
            key = (dpid, stat.port_no)
            self.link_stats[key] = {
                "tx_bytes":   stat.tx_bytes,
                "rx_bytes":   stat.rx_bytes,
                "tx_packets": stat.tx_packets,
                "rx_packets": stat.rx_packets,
                "tx_errors":  stat.tx_errors,
                "timestamp":  time.time(),
            }

    # ── Yönlendirme ───────────────────────────────────────────────
    def _select_output_port(self, dpid, src_mac, dst_mac, in_port):
        """LB-MCR çok yollu port seçimi."""
        dp  = self.datapaths[dpid]
        ofp = dp.ofproto

        if dst_mac in self.mac_to_port[dpid]:
            return self.mac_to_port[dpid][dst_mac]

        # Çok yollu rota varsa yük dengeleme
        path_key = (src_mac, dst_mac)
        if path_key in self.flow_paths and self.flow_paths[path_key]:
            paths = self.flow_paths[path_key]
            # En az yüklü düğümü seçen path
            best_path = min(paths,
                            key=lambda p: self._path_cost(p))
            logger.debug(f"Seçilen path: {best_path}")
            # İlk hop'tan port bul
            if len(best_path) > 1:
                next_hop = best_path[1]
                if next_hop in self.mac_to_port[dpid]:
                    return self.mac_to_port[dpid][next_hop]

        return ofp.OFPP_FLOOD

    def _path_cost(self, path):
        """Bir rotanın toplam maliyeti: enerji + yük + gecikme."""
        cost = 0.0
        for node_id in path:
            if node_id in self.nodes:
                n = self.nodes[node_id]
                # Düşük enerji → yüksek maliyet
                energy_cost = (100.0 - n.energy) / 100.0
                load_cost   = n.load
                cost += 0.5 * energy_cost + 0.5 * load_cost
        return cost

    # ── Kümeleme ──────────────────────────────────────────────────
    def _run_clustering(self):
        """
        Enerji ve bağlantı sayısına göre küme başı seç.
        Yüksek enerjili ve çok komşulu düğümler → küme başı.
        """
        self.clusters.clear()
        for node in self.nodes.values():
            node.is_cluster_head = False
            node.cluster_id      = None

        # Her düğüm için skor hesapla
        scores = {}
        for nid, node in self.nodes.items():
            neighbors = list(self.topology.neighbors(nid))
            n_count   = len(neighbors)
            # UGV'ler her zaman küme başı adayı (sabit enerji)
            if node.node_type == "UGV":
                scores[nid] = 999
            else:
                scores[nid] = (node.energy / 100.0) * 0.6 + \
                              (min(n_count, 5) / 5.0) * 0.4

        # Küme başlarını seç (greedy)
        assigned  = set()
        cluster_id = 0
        for nid in sorted(scores, key=scores.get, reverse=True):
            if nid in assigned:
                continue
            node = self.nodes[nid]
            node.is_cluster_head = True
            node.cluster_id      = cluster_id
            assigned.add(nid)

            members = []
            for neighbor in self.topology.neighbors(nid):
                if neighbor not in assigned:
                    self.nodes[neighbor].cluster_id = cluster_id
                    assigned.add(neighbor)
                    members.append(neighbor)

            self.clusters[cluster_id] = {
                "head":    nid,
                "members": members,
            }
            cluster_id += 1

        heads = [n for n in self.nodes.values() if n.is_cluster_head]
        logger.info(f"Kümeleme tamamlandı: {len(self.clusters)} küme, "
                    f"başlar: {[h.node_id for h in heads]}")
        self._compute_multipath_routes()

    def _compute_multipath_routes(self):
        """Küme başları arasında çok yollu rotalar hesapla."""
        self.flow_paths.clear()
        heads = [nid for nid, n in self.nodes.items()
                 if n.is_cluster_head]

        for i in range(len(heads)):
            for j in range(i + 1, len(heads)):
                src, dst = heads[i], heads[j]
                if not nx.has_path(self.topology, src, dst):
                    continue
                try:
                    paths = list(nx.shortest_simple_paths(
                        self.topology, src, dst,
                        weight="weight"))[:MAX_PATHS]
                    self.flow_paths[(src, dst)] = paths
                    self.flow_paths[(dst, src)] = [
                        list(reversed(p)) for p in paths
                    ]
                    logger.debug(f"Rotalar {src}→{dst}: {len(paths)} path")
                except nx.NetworkXNoPath:
                    pass

    # ── Greedy Onarım ─────────────────────────────────────────────
    def _greedy_repair(self, failed_node_id):
        """
        Bağlantı kopması durumunda coğrafi açgözlü onarım.
        Hedefe en yakın komşuyu bulup yönlendirmeyi günceller.
        """
        logger.warning(f"Greedy onarım başlatıldı: {failed_node_id}")

        if failed_node_id not in self.nodes:
            return

        failed = self.nodes[failed_node_id]

        # Tüm rotaları tara ve etkilenenleri yeniden hesapla
        affected = [(k, v) for k, v in self.flow_paths.items()
                    if any(failed_node_id in p for p in v)]

        for (src, dst), paths in affected:
            if src not in self.nodes or dst not in self.nodes:
                continue

            dst_node = self.nodes[dst]
            candidates = []

            for nid, node in self.nodes.items():
                if nid == failed_node_id:
                    continue
                if node.energy < ENERGY_THRESHOLD:
                    continue
                dist_to_dst = node.distance_to(dst_node)
                dist_to_fail = node.distance_to(failed)
                if dist_to_fail < GREEDY_RADIUS:
                    candidates.append((nid, dist_to_dst))

            if candidates:
                # Hedefe en yakın alternatif düğüm
                best = min(candidates, key=lambda x: x[1])[0]
                # Yeni path oluştur
                try:
                    repair_path = nx.shortest_path(
                        self.topology, src, dst,
                        weight="weight")
                    # Failed düğümü geç
                    if failed_node_id in repair_path:
                        # Onarım için geçici kenar ekle
                        self.topology.add_edge(
                            src, best, weight=1.0,
                            distance=self.nodes[src].distance_to(
                                self.nodes[best]),
                            last_seen=time.time()
                        )
                        repair_path = nx.shortest_path(
                            self.topology, src, dst,
                            weight="weight")

                    self.flow_paths[(src, dst)] = [repair_path]
                    logger.info(f"Onarım tamamlandı {src}→{dst}: "
                                f"{repair_path}")
                    self._log_metric("greedy_repair", src, dst)
                except nx.NetworkXNoPath:
                    logger.error(f"Onarım başarısız: {src}→{dst}")

    # ── Link Ağırlığı ─────────────────────────────────────────────
    def _link_weight(self, n1, n2, dist=None):
        """Kombine link ağırlığı: mesafe + yük + enerji."""
        if dist is None:
            dist = n1.distance_to(n2)
        norm_dist   = dist / 300.0
        avg_energy  = (n1.energy + n2.energy) / 200.0
        avg_load    = (n1.load   + n2.load)   / 2.0
        # Düşük enerji/yüksek yük → ağır kenar
        w = 0.4 * norm_dist + \
            0.4 * (1.0 - avg_energy) + \
            0.2 * avg_load
        return max(0.01, w)

    # ── İzleme Döngüsü ────────────────────────────────────────────
    def _monitor_loop(self):
        """Periyodik: topoloji güncelle, enerji tüket, metrik kaydet."""
        while True:
            hub.sleep(MONITOR_INTERVAL)
            self._update_node_states()
            self._check_link_timeouts()
            self._request_port_stats()
            self._log_metric("monitor")

    def _update_node_states(self):
        """UAV'ların enerjisini güncelle (mobilite simülasyonu)."""
        import random
        for node in self.nodes.values():
            if node.node_type == "UAV":
                # Hareket simülasyonu (rastgele waypoint)
                node.x += random.uniform(-5, 5)
                node.y += random.uniform(-5, 5)
                node.x  = max(0, min(600, node.x))
                node.y  = max(0, min(600, node.y))
                # Enerji tüketimi
                node.update_energy(random.randint(1000, 5000),
                                   MONITOR_INTERVAL)
                # Yük güncelle
                node.load = random.uniform(0.1, 0.9)

            # Kritik enerji uyarısı
            if node.energy < ENERGY_THRESHOLD:
                logger.warning(f"Kritik enerji: {node.node_id} "
                               f"(%.1f%%)" % node.energy)

        # Link ağırlıklarını güncelle
        for u, v in self.topology.edges():
            if u in self.nodes and v in self.nodes:
                w = self._link_weight(self.nodes[u], self.nodes[v])
                self.topology[u][v]['weight'] = w

        # Yeniden kümeleme (her 5 döngüde bir)
        if int(time.time()) % (MONITOR_INTERVAL * 5) == 0:
            self._run_clustering()

    def _check_link_timeouts(self):
        """Eski/kopuk linkleri temizle → greedy onarım tetikle."""
        now     = time.time()
        to_remove = []
        for u, v, data in self.topology.edges(data=True):
            if now - data.get('last_seen', now) > LINK_TIMEOUT:
                to_remove.append((u, v))

        for u, v in to_remove:
            self.topology.remove_edge(u, v)
            logger.warning(f"Link koptu: {u} ↔ {v}")
            self._greedy_repair(u)

    def _request_port_stats(self):
        """Tüm switch'lerden port istatistiği iste."""
        for dp in self.datapaths.values():
            ofp    = dp.ofproto
            parser = dp.ofproto_parser
            req    = parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY)
            dp.send_msg(req)

    # ── Flow Ekleme ───────────────────────────────────────────────
    def _add_flow(self, dp, priority, match, actions,
                  buffer_id=None, idle_timeout=30, hard_timeout=0):
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        inst   = [parser.OFPInstructionActions(
            ofp.OFPIT_APPLY_ACTIONS, actions)]
        kwargs = dict(datapath=dp, priority=priority,
                      match=match, instructions=inst,
                      idle_timeout=idle_timeout,
                      hard_timeout=hard_timeout)
        if buffer_id and buffer_id != ofp.OFP_NO_BUFFER:
            kwargs['buffer_id'] = buffer_id
        dp.send_msg(parser.OFPFlowMod(**kwargs))

    # ── Metrik Kaydı ─────────────────────────────────────────────
    def _log_metric(self, event="", src="", dst=""):
        energies = [n.energy for n in self.nodes.values()]
        avg_e    = sum(energies) / len(energies) if energies else 0

        # Port istatistiklerinden throughput tahmini
        total_tx = sum(s.get("tx_bytes", 0)
                       for s in self.link_stats.values())
        throughput = (total_tx * 8) / (MONITOR_INTERVAL * 1e6)  # Mbps

        self.metrics_writer.writerow([
            time.strftime("%Y-%m-%d %H:%M:%S"),
            event, src, dst,
            f"{throughput:.3f}",
            "0",   # delay: Mininet'ten alınır
            "0",   # loss:  Mininet'ten alınır
            f"{avg_e:.2f}",
            len(self.flow_paths),
        ])
        self.metrics_file.flush()

    def get_topology_json(self):
        """REST API için topoloji JSON'u."""
        return json.dumps({
            "nodes":    [n.to_dict() for n in self.nodes.values()],
            "edges":    [{"src": u, "dst": v, "weight": d.get("weight", 1)}
                         for u, v, d in self.topology.edges(data=True)],
            "clusters": self.clusters,
            "paths":    {str(k): v for k, v in self.flow_paths.items()},
        }, indent=2)
