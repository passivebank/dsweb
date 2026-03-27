export interface Domain {
  name: string;
  tld: string;
  price: string;
  priceNum: number;
  category: string;
  featured?: boolean;
}

export const domains: Domain[] = [
  // Finance
  { name: "CapitalLedger.com", tld: ".com", price: "$24,999", priceNum: 24999, category: "Finance", featured: true },
  { name: "FundBridge.com", tld: ".com", price: "$18,500", priceNum: 18500, category: "Finance" },
  { name: "StakeVault.com", tld: ".com", price: "$12,999", priceNum: 12999, category: "Finance", featured: true },
  { name: "LoanSphere.net", tld: ".net", price: "$4,999", priceNum: 4999, category: "Finance" },
  { name: "DebtClear.com", tld: ".com", price: "$7,999", priceNum: 7999, category: "Finance" },
  { name: "WealthAxis.io", tld: ".io", price: "$8,500", priceNum: 8500, category: "Finance" },

  // Tech
  { name: "CloudForge.com", tld: ".com", price: "$34,999", priceNum: 34999, category: "Tech", featured: true },
  { name: "DevPipeline.io", tld: ".io", price: "$12,500", priceNum: 12500, category: "Tech" },
  { name: "StackNode.com", tld: ".com", price: "$15,999", priceNum: 15999, category: "Tech" },
  { name: "APIVault.io", tld: ".io", price: "$9,999", priceNum: 9999, category: "Tech", featured: true },
  { name: "DataMesh.net", tld: ".net", price: "$6,500", priceNum: 6500, category: "Tech" },
  { name: "SyncLayer.com", tld: ".com", price: "$11,999", priceNum: 11999, category: "Tech" },

  // Health
  { name: "MedReach.com", tld: ".com", price: "$42,000", priceNum: 42000, category: "Health", featured: true },
  { name: "HealthLens.com", tld: ".com", price: "$28,500", priceNum: 28500, category: "Health" },
  { name: "CareMetric.com", tld: ".com", price: "$14,999", priceNum: 14999, category: "Health" },
  { name: "PharmaBridge.net", tld: ".net", price: "$5,999", priceNum: 5999, category: "Health" },
  { name: "WellnessVault.com", tld: ".com", price: "$8,999", priceNum: 8999, category: "Health" },
  { name: "TeleHealth.io", tld: ".io", price: "$85,000", priceNum: 85000, category: "Health", featured: true },

  // Legal
  { name: "CaseBrief.com", tld: ".com", price: "$19,999", priceNum: 19999, category: "Legal" },
  { name: "LegalEdge.com", tld: ".com", price: "$22,500", priceNum: 22500, category: "Legal" },
  { name: "TrialDesk.com", tld: ".com", price: "$7,999", priceNum: 7999, category: "Legal" },
  { name: "DepositLaw.com", tld: ".com", price: "$4,500", priceNum: 4500, category: "Legal" },
  { name: "ClaimPath.net", tld: ".net", price: "$3,999", priceNum: 3999, category: "Legal" },
  { name: "ArbitrateNow.com", tld: ".com", price: "$11,500", priceNum: 11500, category: "Legal" },

  // Real Estate
  { name: "PropertyVault.com", tld: ".com", price: "$38,000", priceNum: 38000, category: "Real Estate" },
  { name: "RealtyPulse.com", tld: ".com", price: "$16,999", priceNum: 16999, category: "Real Estate" },
  { name: "ListingForge.com", tld: ".com", price: "$9,500", priceNum: 9500, category: "Real Estate" },
  { name: "MortgageDesk.net", tld: ".net", price: "$5,500", priceNum: 5500, category: "Real Estate" },
  { name: "HomeBridge.io", tld: ".io", price: "$7,999", priceNum: 7999, category: "Real Estate" },
  { name: "EstateMetric.com", tld: ".com", price: "$2,999", priceNum: 2999, category: "Real Estate" },
];

export const categories = ["All", "Finance", "Tech", "Health", "Legal", "Real Estate"];
export const tlds = ["All", ".com", ".net", ".io"];
