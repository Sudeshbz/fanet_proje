#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/wifi-module.h"
#include "ns3/mobility-module.h"
#include "ns3/applications-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/aodv-module.h"
#include "ns3/olsr-module.h"
#include <fstream>
using namespace ns3;
NS_LOG_COMPONENT_DEFINE("FANET_LB_MCR");

int main(int argc, char *argv[]) {
  std::string protocol = "lbmcr";
  double simTime = 60.0;
  uint32_t nUav = 5;
  CommandLine cmd;
  cmd.AddValue("protocol", "protokol", protocol);
  cmd.AddValue("simTime",  "sure", simTime);
  cmd.AddValue("nUav",     "uav", nUav);
  cmd.Parse(argc, argv);

  NS_LOG_UNCOND("=== FANET: " << protocol << " UAV=" << nUav << " ===");

  NodeContainer uavNodes, ugvNodes, allNodes;
  uavNodes.Create(nUav);
  ugvNodes.Create(2);
  allNodes.Add(uavNodes);
  allNodes.Add(ugvNodes);

  WifiHelper wifi;
  wifi.SetStandard(WIFI_STANDARD_80211g);
  wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager",
    "DataMode",    StringValue("ErpOfdmRate24Mbps"),
    "ControlMode", StringValue("ErpOfdmRate6Mbps"));

  YansWifiPhyHelper phy;
  phy.Set("TxPowerStart", DoubleValue(30.0));
  phy.Set("TxPowerEnd",   DoubleValue(30.0));
  YansWifiChannelHelper channel = YansWifiChannelHelper::Default();
  phy.SetChannel(channel.Create());

  WifiMacHelper mac;
  mac.SetType("ns3::AdhocWifiMac");
  NetDeviceContainer allDevices = wifi.Install(phy, mac, allNodes);

  // Tüm düğümler merkeze yakın küme halinde
  MobilityHelper mobility;
  Ptr<ListPositionAllocator> posAlloc = CreateObject<ListPositionAllocator>();
  posAlloc->Add(Vector(20, 20, 10));  // uav1
  posAlloc->Add(Vector(40, 20, 10));  // uav2
  posAlloc->Add(Vector(60, 20, 10));  // uav3
  posAlloc->Add(Vector(20, 40, 10));  // uav4
  posAlloc->Add(Vector(40, 40, 10));  // uav5
  posAlloc->Add(Vector(30, 30,  0));  // ugv1 - merkez
  posAlloc->Add(Vector(60, 40,  0));  // ugv2
  mobility.SetPositionAllocator(posAlloc);
  mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
  mobility.Install(allNodes);

  InternetStackHelper internet;
  if (protocol == "olsr") {
    OlsrHelper olsr;
    internet.SetRoutingHelper(olsr);
  } else {
    AodvHelper aodv;
    aodv.Set("HelloInterval",      TimeValue(Seconds(0.5)));
    aodv.Set("ActiveRouteTimeout", TimeValue(Seconds(10.0)));
    internet.SetRoutingHelper(aodv);
  }
  internet.Install(allNodes);

  Ipv4AddressHelper ipv4;
  ipv4.SetBase("10.0.0.0", "255.0.0.0");
  Ipv4InterfaceContainer ifaces = ipv4.Assign(allDevices);

  uint16_t port = 9000;
  PacketSinkHelper sink("ns3::UdpSocketFactory",
    InetSocketAddress(Ipv4Address::GetAny(), port));
  ApplicationContainer sinkApp = sink.Install(ugvNodes.Get(0));
  sinkApp.Start(Seconds(1.0));
  sinkApp.Stop(Seconds(simTime));

  Ipv4Address ugv1Addr = ifaces.GetAddress(nUav);
  for (uint32_t i = 0; i < nUav; i++) {
    OnOffHelper onoff("ns3::UdpSocketFactory",
      InetSocketAddress(ugv1Addr, port));
    onoff.SetConstantRate(DataRate("512Kbps"), 512);
    onoff.SetAttribute("StartTime", TimeValue(Seconds(10.0 + i*1.0)));
    onoff.SetAttribute("StopTime",  TimeValue(Seconds(simTime-5.0)));
    onoff.Install(uavNodes.Get(i));
  }

  FlowMonitorHelper flowmon;
  Ptr<FlowMonitor> monitor = flowmon.InstallAll();
  Simulator::Stop(Seconds(simTime+1.0));
  Simulator::Run();

  monitor->CheckForLostPackets();
  Ptr<Ipv4FlowClassifier> classifier =
    DynamicCast<Ipv4FlowClassifier>(flowmon.GetClassifier());

  std::system("mkdir -p /tmp/fanet_results");
  std::ofstream csv("/tmp/fanet_results/ns3_" + protocol + ".csv");
  csv << "flow,src,dst,tx_pkts,rx_pkts,lost,throughput_mbps,delay_ms,loss_pct\n";

  double totalTput=0, totalDelay=0; int nFlows=0;
  for (auto& f : monitor->GetFlowStats()) {
    auto t = classifier->FindFlow(f.first);
    double tput  = (f.second.rxBytes*8.0)/(simTime*1e6);
    double delay = f.second.rxPackets>0 ?
      f.second.delaySum.GetMilliSeconds()/f.second.rxPackets : 0;
    uint32_t lost   = f.second.txPackets - f.second.rxPackets;
    double lostPct  = f.second.txPackets>0 ?
      100.0*lost/f.second.txPackets : 0;
    csv << f.first << "," << t.sourceAddress << ","
        << t.destinationAddress << ","
        << f.second.txPackets << "," << f.second.rxPackets << ","
        << lost << "," << tput << "," << delay << "," << lostPct << "\n";
    NS_LOG_UNCOND("Flow " << f.first
      << " " << t.sourceAddress << "->" << t.destinationAddress
      << " Tput=" << tput << "Mbps"
      << " Delay=" << delay << "ms"
      << " Loss=" << lostPct << "%");
    totalTput+=tput; totalDelay+=delay; nFlows++;
  }
  csv.close();
  if(nFlows>0)
    NS_LOG_UNCOND("=== OZET Tput=" << totalTput/nFlows
      << "Mbps Delay=" << totalDelay/nFlows
      << "ms Flows=" << nFlows << " ===");
  Simulator::Destroy();
  return 0;
}
