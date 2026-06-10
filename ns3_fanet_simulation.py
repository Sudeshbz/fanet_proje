#!/usr/bin/env python3
"""
ns-3 FANET Simülasyonu - LB-MCR Algoritması
TÜBİTAK 2209-A - Sude Filikci

ns-3 Python bindings ile UAV-UGV ağı paket düzeyinde simülasyon.
Çalıştırmak için ns-3 kurulu olmalı:
  cd /path/to/ns-3.xx
  ./waf --run "scratch/fanet_lb_mcr"

YA DA Python bindings varsa:
  python3 ns3_fanet_simulation.py
"""

import sys
import os
import math
import csv
import json
import time
from datetime import datetime

# ─────────────────────────────────────────
# ns-3 Python Bindings
# ─────────────────────────────────────────
try:
    import ns.core
    import ns.network
    import ns.internet
    import ns.wifi
    import ns.mobility
    import ns.applications
    import ns.flow_monitor
    import ns.olsr
    import ns.aodv
    NS3_AVAILABLE = True
except ImportError:
    NS3_AVAILABLE = False
    print("UYARI: ns-3 Python bindings bulunamadı.")
    print("ns-3 C++ script versiyonu üretiliyor...\n")


RESULTS_DIR = "/tmp/fanet_results"
SIM_TIME    = 60.0   # saniye
N_UAV       = 5
N_UGV       = 2
AREA_SIZE   = 600.0  # metre


# ─────────────────────────────────────────
# ns-3 C++ Script Üretici (fallback)
# ─────────────────────────────────────────
def generate_ns3_cpp_script():
    """
    ns-3 C++ simülasyon scripti üret.
    Bu dosya ns-3 scratch/ klasörüne kopyalanır.
    """
    script = '''
/* ============================================================
   FANET LB-MCR ns-3 Simülasyonu
   TÜBİTAK 2209-A - Sude Filikci
   Yalova Üniversitesi
   ============================================================ */

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/wifi-module.h"
#include "ns3/mobility-module.h"
#include "ns3/applications-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/olsr-module.h"
#include "ns3/aodv-module.h"
#include "ns3/stats-module.h"
#include <fstream>
#include <iostream>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("FANET_LB_MCR");

// ─── Parametreler ───────────────────────────────────────────
static const uint32_t N_UAV      = 5;
static const uint32_t N_UGV      = 2;
static const double   SIM_TIME   = 60.0;   // s
static const double   AREA_SIZE  = 600.0;  // m
static const double   TX_POWER   = 20.0;   // dBm
static const double   RX_SENS    = -85.0;  // dBm
static const uint32_t PACKET_SIZE = 1024;  // bytes
static const double   DATA_RATE  = 5.0;    // Mbps

// ─── Enerji Tüketim İzleyici ────────────────────────────────
class EnergyMonitor : public Object {
public:
  static TypeId GetTypeId() {
    static TypeId tid = TypeId("EnergyMonitor")
      .SetParent<Object>()
      .AddConstructor<EnergyMonitor>();
    return tid;
  }
  double totalEnergy = 0.0;
  uint32_t nodeId    = 0;
  void Track(double energy) { totalEnergy += energy; }
};

// ─── Bağlantı Kopma Callback ────────────────────────────────
static uint32_t linkFailures = 0;
void LinkFailureCallback(std::string context) {
  linkFailures++;
  NS_LOG_INFO("Bağlantı kopması: " << context
    << " t=" << Simulator::Now().GetSeconds() << "s");
}

// ─── Ana Fonksiyon ──────────────────────────────────────────
int main(int argc, char *argv[]) {
  // Log seviyeleri
  LogComponentEnable("FANET_LB_MCR", LOG_LEVEL_INFO);
  LogComponentEnable("UdpClient",     LOG_LEVEL_INFO);

  // Komut satırı argümanları
  std::string protocol   = "lbmcr";  // lbmcr | aodv | olsr
  double      simTime    = SIM_TIME;
  uint32_t    nUav       = N_UAV;
  bool        pcapOutput = false;

  CommandLine cmd;
  cmd.AddValue("protocol",   "Yönlendirme protokolü (lbmcr|aodv|olsr)", protocol);
  cmd.AddValue("simTime",    "Simülasyon süresi (s)",                    simTime);
  cmd.AddValue("nUav",       "UAV sayısı",                               nUav);
  cmd.AddValue("pcap",       "PCAP çıktısı",                             pcapOutput);
  cmd.Parse(argc, argv);

  NS_LOG_INFO("=== FANET Simülasyonu Başlıyor ===");
  NS_LOG_INFO("Protokol: " << protocol << "  UAV: " << nUav
    << "  Süre: " << simTime << "s");

  // ── Düğüm Oluştur ──────────────────────────────────────────
  NodeContainer uavNodes, ugvNodes, allNodes;
  uavNodes.Create(nUav);
  ugvNodes.Create(N_UGV);
  allNodes.Add(uavNodes);
  allNodes.Add(ugvNodes);

  // ── WiFi (802.11g Ad-Hoc) ──────────────────────────────────
  WifiHelper wifi;
  wifi.SetStandard(WIFI_STANDARD_80211g);
  wifi.SetRemoteStationManager(
    "ns3::ConstantRateWifiManager",
    "DataMode",    StringValue("ErpOfdmRate54Mbps"),
    "ControlMode", StringValue("ErpOfdmRate6Mbps")
  );

  YansWifiPhyHelper phy;
  phy.Set("TxPowerStart",  DoubleValue(TX_POWER));
  phy.Set("TxPowerEnd",    DoubleValue(TX_POWER));
  phy.Set("RxSensitivity", DoubleValue(RX_SENS));
  phy.Set("ChannelWidth",  UintegerValue(20));

  // Log-distance propagation
  YansWifiChannelHelper channel;
  channel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
  channel.AddPropagationLoss(
    "ns3::LogDistancePropagationLossModel",
    "Exponent", DoubleValue(3.0),
    "ReferenceDistance", DoubleValue(1.0),
    "ReferenceLoss",     DoubleValue(46.677)
  );
  phy.SetChannel(channel.Create());

  WifiMacHelper mac;
  mac.SetType("ns3::AdhocWifiMac");

  NetDeviceContainer uavDevices = wifi.Install(phy, mac, uavNodes);
  NetDeviceContainer ugvDevices = wifi.Install(phy, mac, ugvNodes);
  NetDeviceContainer allDevices;
  allDevices.Add(uavDevices);
  allDevices.Add(ugvDevices);

  // ── Mobilite ───────────────────────────────────────────────
  MobilityHelper mobility;

  // UAV: Random Waypoint (hareketli)
  mobility.SetPositionAllocator(
    "ns3::RandomRectanglePositionAllocator",
    "X", StringValue("ns3::UniformRandomVariable[Min=50|Max=550]"),
    "Y", StringValue("ns3::UniformRandomVariable[Min=50|Max=550]")
  );
  mobility.SetMobilityModel(
    "ns3::RandomWaypointMobilityModel",
    "Speed",  StringValue("ns3::UniformRandomVariable[Min=1|Max=15]"),
    "Pause",  StringValue("ns3::ConstantRandomVariable[Constant=0.5]"),
    "PositionAllocator",
      StringValue("ns3::RandomRectanglePositionAllocator"
                  "|X=ns3::UniformRandomVariable[Min=50|Max=550]"
                  "|Y=ns3::UniformRandomVariable[Min=50|Max=550]")
  );
  mobility.Install(uavNodes);

  // UGV: Sabit (Constant Position)
  Ptr<ListPositionAllocator> ugvAlloc =
    CreateObject<ListPositionAllocator>();
  ugvAlloc->Add(Vector(50,  50,  0));
  ugvAlloc->Add(Vector(550, 500, 0));
  mobility.SetPositionAllocator(ugvAlloc);
  mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
  mobility.Install(ugvNodes);

  // ── Internet Stack ─────────────────────────────────────────
  InternetStackHelper internet;

  if (protocol == "aodv") {
    AodvHelper aodv;
    internet.SetRoutingHelper(aodv);
    NS_LOG_INFO("AODV yönlendirme aktif");
  } else if (protocol == "olsr") {
    OlsrHelper olsr;
    internet.SetRoutingHelper(olsr);
    NS_LOG_INFO("OLSR yönlendirme aktif");
  } else {
    // LB-MCR: AODV tabanlı özelleştirilmiş (tam SDN impl C++ gerektirir)
    AodvHelper aodv;
    aodv.Set("HelloInterval",  TimeValue(Seconds(0.5)));
    aodv.Set("ActiveRouteTimeout", TimeValue(Seconds(3)));
    internet.SetRoutingHelper(aodv);
    NS_LOG_INFO("LB-MCR (AODV base) yönlendirme aktif");
  }

  internet.Install(allNodes);

  // ── IP Adresleri ────────────────────────────────────────────
  Ipv4AddressHelper ipv4;
  ipv4.SetBase("10.0.0.0", "255.0.0.0");
  Ipv4InterfaceContainer interfaces = ipv4.Assign(allDevices);

  // ── Uygulamalar ─────────────────────────────────────────────
  // UDP akışı: her UAV → UGV1
  uint16_t port = 9000;
  Ptr<Node> ugv1 = ugvNodes.Get(0);
  Ipv4Address ugv1Addr = interfaces.GetAddress(nUav);  // UGV1 IP

  // Sink (alıcı) - UGV1
  PacketSinkHelper sink("ns3::UdpSocketFactory",
    InetSocketAddress(Ipv4Address::GetAny(), port));
  ApplicationContainer sinkApps = sink.Install(ugv1);
  sinkApps.Start(Seconds(0.5));
  sinkApps.Stop(Seconds(simTime));

  // Kaynak (gönderici) - UAV'lar
  for (uint32_t i = 0; i < nUav; i++) {
    OnOffHelper onoff("ns3::UdpSocketFactory",
      InetSocketAddress(ugv1Addr, port + i));
    onoff.SetConstantRate(DataRate(
      std::to_string((int)(DATA_RATE * 1e6 / nUav)) + "bps"),
      PACKET_SIZE);
    onoff.SetAttribute("StartTime",
      TimeValue(Seconds(1.0 + i * 0.2)));
    onoff.SetAttribute("StopTime",
      TimeValue(Seconds(simTime - 1.0)));
    onoff.Install(uavNodes.Get(i));
  }

  // UAV-UAV akışı (çok yollu test)
  OnOffHelper uavUav("ns3::UdpSocketFactory",
    InetSocketAddress(interfaces.GetAddress(nUav-1), port + 100));
  uavUav.SetConstantRate(DataRate("2Mbps"), PACKET_SIZE);
  uavUav.SetAttribute("StartTime",  TimeValue(Seconds(2.0)));
  uavUav.SetAttribute("StopTime",   TimeValue(Seconds(simTime - 2.0)));
  uavUav.Install(uavNodes.Get(0));

  PacketSinkHelper uavSink("ns3::UdpSocketFactory",
    InetSocketAddress(Ipv4Address::GetAny(), port + 100));
  ApplicationContainer uavSinkApps = uavSink.Install(uavNodes.Get(nUav-1));
  uavSinkApps.Start(Seconds(0.5));
  uavSinkApps.Stop(Seconds(simTime));

  // ── FlowMonitor ─────────────────────────────────────────────
  FlowMonitorHelper flowmon;
  Ptr<FlowMonitor> monitor = flowmon.InstallAll();

  // ── PCAP ────────────────────────────────────────────────────
  if (pcapOutput) {
    phy.SetPcapDataLinkType(WifiPhyHelper::DLT_IEEE802_11_RADIO);
    phy.EnablePcapAll("fanet_lb_mcr");
  }

  // ── Simülasyon Çalıştır ─────────────────────────────────────
  NS_LOG_INFO("Simülasyon başlıyor...");
  Simulator::Stop(Seconds(simTime + 0.5));
  Simulator::Run();

  // ── Sonuçları Topla ─────────────────────────────────────────
  monitor->CheckForLostPackets();
  Ptr<Ipv4FlowClassifier> classifier =
    DynamicCast<Ipv4FlowClassifier>(flowmon.GetClassifier());
  FlowMonitor::FlowStatsContainer stats = monitor->GetFlowStats();

  std::ofstream csvFile("/tmp/fanet_results/ns3_results.csv");
  csvFile << "flow_id,src_ip,dst_ip,tx_packets,rx_packets,"
             "lost_packets,throughput_mbps,delay_ms,jitter_ms,"
             "packet_loss_pct\\n";

  double totalThroughput = 0;
  double totalDelay      = 0;
  uint32_t totalFlows    = 0;

  for (auto& flow : stats) {
    Ipv4FlowClassifier::FiveTuple t =
      classifier->FindFlow(flow.first);

    double rxBytes = flow.second.rxBytes;
    double elapsed = simTime;
    double tput    = (rxBytes * 8.0) / (elapsed * 1e6);

    double avgDelay = 0;
    if (flow.second.rxPackets > 0) {
      avgDelay = flow.second.delaySum.GetMilliSeconds()
                 / flow.second.rxPackets;
    }

    double jitter = 0;
    if (flow.second.rxPackets > 1) {
      jitter = flow.second.jitterSum.GetMilliSeconds()
               / (flow.second.rxPackets - 1);
    }

    uint32_t lost = flow.second.txPackets - flow.second.rxPackets;
    double   lostPct = (flow.second.txPackets > 0)
      ? 100.0 * lost / flow.second.txPackets : 0;

    csvFile << flow.first << ","
            << t.sourceAddress      << ","
            << t.destinationAddress << ","
            << flow.second.txPackets << ","
            << flow.second.rxPackets << ","
            << lost    << ","
            << tput    << ","
            << avgDelay << ","
            << jitter  << ","
            << lostPct << "\\n";

    NS_LOG_INFO("Flow " << flow.first
      << " | " << t.sourceAddress << " → " << t.destinationAddress
      << " | Throughput=" << tput << " Mbps"
      << " | Delay=" << avgDelay << " ms"
      << " | Loss=" << lostPct << "%");

    totalThroughput += tput;
    totalDelay      += avgDelay;
    totalFlows++;
  }
  csvFile.close();

  // Özet
  NS_LOG_INFO("=== ÖZET ===");
  NS_LOG_INFO("Toplam akış: " << totalFlows);
  if (totalFlows > 0) {
    NS_LOG_INFO("Ort. Throughput: "
      << totalThroughput/totalFlows << " Mbps");
    NS_LOG_INFO("Ort. Gecikme: "
      << totalDelay/totalFlows << " ms");
  }
  NS_LOG_INFO("Link kopması: " << linkFailures);

  // XML FlowMonitor çıktısı
  monitor->SerializeToXmlFile(
    "/tmp/fanet_results/flowmonitor.xml", true, true);

  Simulator::Destroy();
  NS_LOG_INFO("Simülasyon tamamlandı.");
  return 0;
}
'''
    return script


# ─────────────────────────────────────────
# Python ns-3 Simülasyonu
# ─────────────────────────────────────────
def run_ns3_python_simulation():
    """ns-3 Python bindings ile simülasyon."""
    import ns.core as core
    import ns.network as network
    import ns.internet as internet
    import ns.wifi as wifi
    import ns.mobility as mobility
    import ns.applications as apps

    core.LogComponentEnable("UdpClient", core.LOG_LEVEL_INFO)

    # Düğümler
    uavs = network.NodeContainer()
    ugvs = network.NodeContainer()
    uavs.Create(N_UAV)
    ugvs.Create(N_UGV)

    all_nodes = network.NodeContainer()
    all_nodes.Add(uavs)
    all_nodes.Add(ugvs)

    # WiFi
    wifi_helper = wifi.WifiHelper()
    wifi_helper.SetStandard(wifi.WIFI_STANDARD_80211g)

    phy = wifi.YansWifiPhyHelper()
    channel = wifi.YansWifiChannelHelper.Default()
    phy.SetChannel(channel.Create())

    mac = wifi.WifiMacHelper()
    mac.SetType("ns3::AdhocWifiMac")

    all_devs = wifi_helper.Install(phy, mac, all_nodes)

    # Mobilite
    mob = mobility.MobilityHelper()
    mob.SetMobilityModel("ns3::RandomWaypointMobilityModel",
                         "Speed",
                         core.StringValue(
                             "ns3::UniformRandomVariable[Min=1|Max=10]"),
                         "Pause",
                         core.StringValue(
                             "ns3::ConstantRandomVariable[Constant=0.5]"))
    mob.Install(uavs)

    pos_alloc = mobility.ListPositionAllocator()
    pos_alloc.Add(core.Vector(50, 50, 0))
    pos_alloc.Add(core.Vector(550, 500, 0))
    mob.SetPositionAllocator(pos_alloc)
    mob.SetMobilityModel("ns3::ConstantPositionMobilityModel")
    mob.Install(ugvs)

    # Internet
    internet_stack = internet.InternetStackHelper()
    internet_stack.Install(all_nodes)

    ipv4 = internet.Ipv4AddressHelper()
    ipv4.SetBase("10.0.0.0", "255.0.0.0")
    ifaces = ipv4.Assign(all_devs)

    # UDP Sink
    sink = apps.PacketSinkHelper(
        "ns3::UdpSocketFactory",
        network.InetSocketAddress(
            network.Ipv4Address.GetAny(), 9))
    sink_apps = sink.Install(ugvs.Get(0))
    sink_apps.Start(core.Seconds(0.5))
    sink_apps.Stop(core.Seconds(SIM_TIME))

    # OnOff Sources
    ugv1_addr = ifaces.GetAddress(N_UAV)
    for i in range(N_UAV):
        onoff = apps.OnOffHelper(
            "ns3::UdpSocketFactory",
            network.InetSocketAddress(ugv1_addr, 9))
        onoff.SetConstantRate(
            network.DataRate("1Mbps"), 1024)
        onoff.SetAttribute("StartTime",
                           core.TimeValue(core.Seconds(1.0 + i * 0.2)))
        onoff.SetAttribute("StopTime",
                           core.TimeValue(core.Seconds(SIM_TIME - 1.0)))
        onoff.Install(uavs.Get(i))

    # Simülasyon
    core.Simulator.Stop(core.Seconds(SIM_TIME))
    core.Simulator.Run()
    core.Simulator.Destroy()

    print("ns-3 Python simülasyonu tamamlandı.")


# ─────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────
def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    if NS3_AVAILABLE:
        print("ns-3 Python bindings bulundu, simülasyon çalıştırılıyor...")
        run_ns3_python_simulation()
    else:
        print("ns-3 Python bindings yok.")
        print("C++ script üretiliyor...\n")
        script = generate_ns3_cpp_script()

        out_path = "/home/ubuntu/ns3_fanet_lb_mcr.cc"
        with open(out_path, "w") as f:
            f.write(script)
        print(f"C++ script kaydedildi: {out_path}")
        print("\nKullanım:")
        print("  cp /home/ubuntu/ns3_fanet_lb_mcr.cc ~/ns-allinone-3.xx/ns-3.xx/scratch/")
        print("  cd ~/ns-allinone-3.xx/ns-3.xx")
        print("  ./waf build")
        print("  ./waf --run 'fanet_lb_mcr --protocol=lbmcr --nUav=5 --simTime=60'")
        print("  ./waf --run 'fanet_lb_mcr --protocol=aodv  --nUav=5 --simTime=60'")
        print("  ./waf --run 'fanet_lb_mcr --protocol=olsr  --nUav=5 --simTime=60'")
        print("\nSonuçlar: /tmp/fanet_results/ns3_results.csv")


if __name__ == "__main__":
    main()
