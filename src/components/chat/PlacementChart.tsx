import { Card } from "@/components/ui/card";

const PlacementChart = () => {
  const data = [
    { year: "2021", percentage: 85, color: "bg-primary/60" },
    { year: "2022", percentage: 90, color: "bg-primary/70" },
    { year: "2023", percentage: 92, color: "bg-primary/80" },
    { year: "2024", percentage: 95, color: "bg-primary" },
  ];

  return (
    <div className="flex w-full justify-start animate-fade-in-up">
      <Card className="max-w-[90%] p-6 bg-card shadow-card">
        <h3 className="text-sm font-semibold mb-4 text-foreground">
          Placement Statistics
        </h3>
        <div className="space-y-4">
          {data.map((item, index) => (
            <div key={index} className="space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-foreground">{item.year}</span>
                <span className="text-muted-foreground">{item.percentage}%</span>
              </div>
              <div className="h-8 bg-muted rounded-lg overflow-hidden">
                <div
                  className={`h-full ${item.color} transition-all duration-1000 ease-out flex items-center justify-end pr-2`}
                  style={{
                    width: `${item.percentage}%`,
                    animationDelay: `${index * 0.1}s`,
                  }}
                >
                  <span className="text-xs font-medium text-white">
                    {item.percentage}%
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 pt-4 border-t border-border">
          <p className="text-xs text-muted-foreground">
            📈 Average package increased by 15% in 2024
          </p>
        </div>
      </Card>
    </div>
  );
};

export default PlacementChart;
