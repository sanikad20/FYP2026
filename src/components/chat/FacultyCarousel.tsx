import { Card } from "@/components/ui/card";
import { Mail, Phone } from "lucide-react";

const FacultyCarousel = () => {
  const faculty = [
    {
      name: "Dr. Sarah Johnson",
      department: "Computer Science",
      email: "s.johnson@campus.edu",
      phone: "+1 234-567-8901",
    },
    {
      name: "Prof. Michael Chen",
      department: "Data Science",
      email: "m.chen@campus.edu",
      phone: "+1 234-567-8902",
    },
    {
      name: "Dr. Emily Williams",
      department: "Software Engineering",
      email: "e.williams@campus.edu",
      phone: "+1 234-567-8903",
    },
  ];

  return (
    <div className="flex w-full justify-start animate-fade-in-up">
      <div className="w-full max-w-full overflow-hidden">
        <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-hide">
          {faculty.map((member, index) => (
            <Card
              key={index}
              className="min-w-[280px] p-4 bg-gradient-to-br from-card to-primary-light/20 border-primary/10 shadow-card hover:shadow-elevated transition-all duration-300 hover:-translate-y-1"
            >
              <div className="flex items-start gap-3">
                <div className="h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                  <span className="text-lg font-semibold text-primary">
                    {member.name.split(" ").map(n => n[0]).join("")}
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-sm text-foreground truncate">
                    {member.name}
                  </h3>
                  <p className="text-xs text-muted-foreground mb-2">
                    {member.department}
                  </p>
                  <div className="space-y-1">
                    <div className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Mail className="h-3 w-3 flex-shrink-0" />
                      <span className="truncate">{member.email}</span>
                    </div>
                    <div className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Phone className="h-3 w-3 flex-shrink-0" />
                      <span>{member.phone}</span>
                    </div>
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
};

export default FacultyCarousel;
