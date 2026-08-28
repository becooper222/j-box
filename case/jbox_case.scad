// J-Box enclosure - parametric lidded box
// Three parts, all printing flat with no supports:
//   1. body   - the box, cavity up
//   2. bezel  - top plate with screen aperture, prints face down
//   3. lid    - hinged lid with magnet pocket, prints top down
//
// !!! MEASURE BEFORE PRINTING !!!
// The values marked MEASURE are close for the Waveshare 4inch HDMI LCD +
// Pi Zero 2 stack, but verify each with calipers or a good ruler, and do a
// quick test print of test_aperture() first (a thin frame to check the
// screen fit without printing the whole box).

/* ======================= measurements ======================= */

screen_w        = 86.0;   // MEASURE: screen PCB width  (mm)
screen_h        = 56.5;   // MEASURE: screen PCB height (mm)
screen_thick    = 6.5;    // MEASURE: PCB top to glass face
active_w        = 81.0;   // MEASURE: visible display width
active_h        = 49.0;   // MEASURE: visible display height
active_off_x    = 2.5;    // MEASURE: left PCB edge -> visible area
active_off_y    = 4.0;    // MEASURE: top PCB edge -> visible area
mount_dx        = 58.0;   // screen mounting holes X spacing (Pi standard)
mount_dy        = 49.0;   // screen mounting holes Y spacing
stack_height    = 38.0;   // MEASURE: screen back to lowest point of the
                          // Pi + hub HAT + HDMI adapter stack, plus slack

wall            = 3.0;
floor_t         = 3.0;
bezel_t         = 3.0;
clearance       = 0.6;    // fit slack around the screen PCB

cavity_w = screen_w + 2*clearance + 14;   // room for cables at the sides
cavity_d = screen_h + 2*clearance + 14;
cavity_h = stack_height + screen_thick + 4;

box_w = cavity_w + 2*wall;
box_d = cavity_d + 2*wall;
box_h = cavity_h + floor_t;

lid_h        = 12;        // inner depth of the lid dome
hinge_r      = 4;
hinge_pin_d  = 3.2;       // 3mm filament or nail as the hinge pin
led_d        = 5.4;       // 5mm LED press fit in the front face
button_d     = 12.2;      // MEASURE your button's threaded barrel
button_gap   = 26;        // spacing between the LED and the button
cable_w      = 12;        // USB power cable exit
magnet_d     = 8.4;       // MEASURE your magnet (8x3 disc assumed)
magnet_t     = 3.2;
reed_l       = 16;        // reed switch pocket in the front wall
reed_d       = 3.0;

$fn = 48;

/* ======================= parts ======================= */

module body() {
  difference() {
    // outer shell, rounded verticals
    linear_extrude(box_h) offset(3) offset(-3) square([box_w, box_d]);
    // cavity
    translate([wall, wall, floor_t]) cube([cavity_w, cavity_d, box_h]);
    // LED and heart button on the front face, flanking the centre
    translate([box_w/2 - button_gap/2, wall+1, box_h - 12])
      rotate([90,0,0]) cylinder(h=wall+2, d=led_d);
    translate([box_w/2 + button_gap/2, wall+1, box_h - 12])
      rotate([90,0,0]) cylinder(h=wall+2, d=button_d);
    // reed switch pocket: horizontal channel inside the front wall
    translate([box_w/2 - reed_l/2, wall - reed_d - 0.6, box_h - 6])
      cube([reed_l, reed_d, reed_d]);
    // power cable exit, back wall at floor level
    translate([box_w/2 - cable_w/2, box_d - wall - 1, floor_t])
      cube([cable_w, wall + 2, 8]);
    // bottom vents
    for (i = [-2:2])
      translate([box_w/2 + i*10 - 2, box_d/2 - 15, -1]) cube([4, 30, floor_t+2]);
    // bezel screw holes (self-tapping M2.5 into the wall tops)
    bezel_screws() cylinder(h=12, d=2.2, center=true);
  }
  // hinge knuckles on the back top edge (outer pair; lid takes the middle)
  for (x = [box_w*0.2, box_w*0.8])
    translate([x, box_d, box_h - hinge_r]) hinge_knuckle(8);
}

module hinge_knuckle(len) {
  rotate([0,90,0]) difference() {
    union() {
      cylinder(h=len, d=2*hinge_r, center=true);
      translate([hinge_r/2, 0, 0]) cube([hinge_r, 2*hinge_r, len], center=true);
    }
    cylinder(h=len+2, d=hinge_pin_d, center=true);
  }
}

module bezel_screws() {
  for (p = [[8,8],[box_w-8,8],[8,box_d-8],[box_w-8,box_d-8]])
    translate([p[0], p[1], box_h]) children();
}

module bezel() {
  ax = (box_w - active_w)/2 + (active_off_x - (screen_w - active_w)/2);
  ay = (box_d - active_h)/2 + (active_off_y - (screen_h - active_h)/2);
  difference() {
    linear_extrude(bezel_t) offset(3) offset(-3) square([box_w, box_d]);
    // aperture with a small chamfer so the glass edge is framed cleanly
    translate([ax, ay, -1]) cube([active_w, active_h, bezel_t + 2]);
    translate([ax-1.5, ay-1.5, bezel_t-1.2]) cube([active_w+3, active_h+3, 2]);
    bezel_screws_flat() cylinder(h=bezel_t+2, d=3.0);
  }
  // posts that press the screen PCB down onto the wall ledge
  for (sx = [-1,1], sy = [-1,1])
    translate([box_w/2 + sx*mount_dx/2, box_d/2 + sy*mount_dy/2, bezel_t])
      difference() {
        cylinder(h=screen_thick, d=7);
        cylinder(h=screen_thick+1, d=2.4);  // M2.5 self-tap into screen holes
      }
}

module bezel_screws_flat() {
  for (p = [[8,8],[box_w-8,8],[8,box_d-8],[box_w-8,box_d-8]])
    translate([p[0], p[1], -1]) children();
}

module lid() {
  difference() {
    union() {
      linear_extrude(6) offset(3) offset(-3) square([box_w, box_d]);
      // skirt that overlaps the box rim
      translate([1.5, 1.5, 0]) linear_extrude(6 + 4)
        difference() {
          offset(3) offset(-3) square([box_w-3, box_d-3]);
          offset(-2.5) offset(3) offset(-3) square([box_w-3, box_d-3]);
        }
    }
    // magnet pocket in the front underside, above the reed switch
    translate([box_w/2, wall + reed_d/2, 6 - magnet_t])
      cylinder(h=magnet_t + 1, d=magnet_d);
  }
  // middle hinge knuckle, meshes between the body's pair
  translate([box_w/2, box_d, hinge_r]) hinge_knuckle(box_w*0.6 - 16);
}

// thin frame for test-fitting the screen before committing to a full print
module test_aperture() {
  intersection() {
    bezel();
    translate([-1,-1,-1]) cube([box_w+2, box_d+2, bezel_t+1]);
  }
}

/* ======================= layout ======================= */
// Render one part at a time and export STL: set PART below.
PART = "all"; // "body" | "bezel" | "lid" | "test" | "all"

if (PART == "body") body();
else if (PART == "bezel") bezel();
else if (PART == "lid") lid();
else if (PART == "test") test_aperture();
else {
  body();
  translate([box_w + 15, 0, 0]) bezel();
  translate([0, -(box_d + 25), 0]) lid();
}
