(define (problem truck-7)
(:domain Trucks)

(:objects
	truck1 - truck
	package1 - package
	package2 - package
	package3 - package
	package4 - package
	package5 - package
	package6 - package
	l1 - location
	l2 - location
	l3 - location
	l4 - location
	t0 - time
	t1 - time
	t2 - time
	t3 - time
	t4 - time
	t5 - time
	t6 - time
	t7 - time
	t8 - time
	a1 - truckarea
	a2 - truckarea
	a3 - truckarea
	d21 - mile
	d25 - mile
	d26 - mile
	d27 - mile
	d34 - mile
	d47 - mile
	s25 - mph
	s40 - mph
	s50 - mph
	s55 - mph
	s65 - mph
	c3 - gridcoord
	c4 - gridcoord
	c12 - gridcoord
	c20 - gridcoord
	c29 - gridcoord
	c34 - gridcoord
	c38 - gridcoord
	c39 - gridcoord
)

(:init
	(at truck1 l3)
	(free a1 truck1)
	(free a2 truck1)
	(free a3 truck1)
	(closer a1 a2)
	(closer a1 a3)
	(closer a2 a3)
	(at package1 l1)
	(at package2 l1)
	(at package3 l1)
	(at package4 l1)
	(at package5 l1)
	(at package6 l1)
	(connected l1 l2)
	(connected l1 l3)
	(connected l1 l4)
	(connected l2 l1)
	(connected l2 l3)
	(connected l2 l4)
	(connected l3 l1)
	(connected l3 l2)
	(connected l3 l4)
	(connected l4 l1)
	(connected l4 l2)
	(connected l4 l3)
	(time-now t0)
	(le t1 t1)
	(le t1 t2)
	(le t1 t3)
	(le t1 t4)
	(le t1 t5)
	(le t1 t6)
	(le t1 t7)
	(le t1 t8)
	(le t2 t2)
	(le t2 t3)
	(le t2 t4)
	(le t2 t5)
	(le t2 t6)
	(le t2 t7)
	(le t2 t8)
	(le t3 t3)
	(le t3 t4)
	(le t3 t5)
	(le t3 t6)
	(le t3 t7)
	(le t3 t8)
	(le t4 t4)
	(le t4 t5)
	(le t4 t6)
	(le t4 t7)
	(le t4 t8)
	(le t5 t5)
	(le t5 t6)
	(le t5 t7)
	(le t5 t8)
	(le t6 t6)
	(le t6 t7)
	(le t6 t8)
	(le t7 t7)
	(le t7 t8)
	(le t8 t8)
	(next t0 t1)
	(next t1 t2)
	(next t2 t3)
	(next t3 t4)
	(next t4 t5)
	(next t5 t6)
	(next t6 t7)
	(next t7 t8)
	(loc-x l1 c3)
	(loc-y l1 c39)
	(loc-x l2 c12)
	(loc-y l2 c20)
	(loc-x l3 c34)
	(loc-y l3 c4)
	(loc-x l4 c29)
	(loc-y l4 c38)
	(road-distance l1 l2 d21)
	(road-speed l1 l2 s40)
	(road-span l1 l2 t0 t1)
	(road-span l1 l2 t1 t2)
	(road-span l1 l2 t2 t3)
	(road-span l1 l2 t3 t4)
	(road-span l1 l2 t4 t5)
	(road-span l1 l2 t5 t6)
	(road-span l1 l2 t6 t7)
	(road-span l1 l2 t7 t8)
	(road-distance l1 l3 d47)
	(road-speed l1 l3 s65)
	(road-span l1 l3 t0 t1)
	(road-span l1 l3 t1 t2)
	(road-span l1 l3 t2 t3)
	(road-span l1 l3 t3 t4)
	(road-span l1 l3 t4 t5)
	(road-span l1 l3 t5 t6)
	(road-span l1 l3 t6 t7)
	(road-span l1 l3 t7 t8)
	(road-distance l1 l4 d26)
	(road-speed l1 l4 s55)
	(zero-time-road l1 l4)
	(road-distance l2 l1 d21)
	(road-speed l2 l1 s40)
	(road-span l2 l1 t0 t1)
	(road-span l2 l1 t1 t2)
	(road-span l2 l1 t2 t3)
	(road-span l2 l1 t3 t4)
	(road-span l2 l1 t4 t5)
	(road-span l2 l1 t5 t6)
	(road-span l2 l1 t6 t7)
	(road-span l2 l1 t7 t8)
	(road-distance l2 l3 d27)
	(road-speed l2 l3 s25)
	(road-span l2 l3 t0 t1)
	(road-span l2 l3 t1 t2)
	(road-span l2 l3 t2 t3)
	(road-span l2 l3 t3 t4)
	(road-span l2 l3 t4 t5)
	(road-span l2 l3 t5 t6)
	(road-span l2 l3 t6 t7)
	(road-span l2 l3 t7 t8)
	(road-distance l2 l4 d25)
	(road-speed l2 l4 s25)
	(road-span l2 l4 t0 t1)
	(road-span l2 l4 t1 t2)
	(road-span l2 l4 t2 t3)
	(road-span l2 l4 t3 t4)
	(road-span l2 l4 t4 t5)
	(road-span l2 l4 t5 t6)
	(road-span l2 l4 t6 t7)
	(road-span l2 l4 t7 t8)
	(road-distance l3 l1 d47)
	(road-speed l3 l1 s65)
	(road-span l3 l1 t0 t1)
	(road-span l3 l1 t1 t2)
	(road-span l3 l1 t2 t3)
	(road-span l3 l1 t3 t4)
	(road-span l3 l1 t4 t5)
	(road-span l3 l1 t5 t6)
	(road-span l3 l1 t6 t7)
	(road-span l3 l1 t7 t8)
	(road-distance l3 l2 d27)
	(road-speed l3 l2 s25)
	(road-span l3 l2 t0 t1)
	(road-span l3 l2 t1 t2)
	(road-span l3 l2 t2 t3)
	(road-span l3 l2 t3 t4)
	(road-span l3 l2 t4 t5)
	(road-span l3 l2 t5 t6)
	(road-span l3 l2 t6 t7)
	(road-span l3 l2 t7 t8)
	(road-distance l3 l4 d34)
	(road-speed l3 l4 s50)
	(road-span l3 l4 t0 t1)
	(road-span l3 l4 t1 t2)
	(road-span l3 l4 t2 t3)
	(road-span l3 l4 t3 t4)
	(road-span l3 l4 t4 t5)
	(road-span l3 l4 t5 t6)
	(road-span l3 l4 t6 t7)
	(road-span l3 l4 t7 t8)
	(road-distance l4 l1 d26)
	(road-speed l4 l1 s55)
	(zero-time-road l4 l1)
	(road-distance l4 l2 d25)
	(road-speed l4 l2 s25)
	(road-span l4 l2 t0 t1)
	(road-span l4 l2 t1 t2)
	(road-span l4 l2 t2 t3)
	(road-span l4 l2 t3 t4)
	(road-span l4 l2 t4 t5)
	(road-span l4 l2 t5 t6)
	(road-span l4 l2 t6 t7)
	(road-span l4 l2 t7 t8)
	(road-distance l4 l3 d34)
	(road-speed l4 l3 s50)
	(road-span l4 l3 t0 t1)
	(road-span l4 l3 t1 t2)
	(road-span l4 l3 t2 t3)
	(road-span l4 l3 t3 t4)
	(road-span l4 l3 t4 t5)
	(road-span l4 l3 t5 t6)
	(road-span l4 l3 t6 t7)
	(road-span l4 l3 t7 t8)
)

(:goal (and 
	(delivered package1 l3 t4)
	(delivered package2 l3 t4)
	(delivered package3 l2 t4)
	(delivered package4 l2 t8)
	(at-destination package5 l3)
	(delivered package6 l3 t8)
))

)
