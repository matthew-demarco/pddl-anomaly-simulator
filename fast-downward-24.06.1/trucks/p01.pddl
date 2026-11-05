(define (problem truck-1)
(:domain Trucks)

(:objects
	truck1 - truck
	package1 - package
	package2 - package
	package3 - package
	l1 - location
	l2 - location
	l3 - location
	t0 - time
	t1 - time
	t2 - time
	t3 - time
	t4 - time
	t5 - time
	t6 - time
	a1 - truckarea
	a2 - truckarea
	d21 - mile
	d23 - mile
	d31 - mile
	s40 - mph
	s50 - mph
	s65 - mph
	c4 - gridcoord
	c6 - gridcoord
	c11 - gridcoord
	c13 - gridcoord
	c25 - gridcoord
	c36 - gridcoord
)

(:init
	(at truck1 l3)
	(free a1 truck1)
	(free a2 truck1)
	(closer a1 a2)
	(at package1 l2)
	(at package2 l2)
	(at package3 l2)
	(connected l1 l2)
	(connected l1 l3)
	(connected l2 l1)
	(connected l2 l3)
	(connected l3 l1)
	(connected l3 l2)
	(time-now t0)
	(le t1 t1)
	(le t1 t2)
	(le t1 t3)
	(le t1 t4)
	(le t1 t5)
	(le t1 t6)
	(le t2 t2)
	(le t2 t3)
	(le t2 t4)
	(le t2 t5)
	(le t2 t6)
	(le t3 t3)
	(le t3 t4)
	(le t3 t5)
	(le t3 t6)
	(le t4 t4)
	(le t4 t5)
	(le t4 t6)
	(le t5 t5)
	(le t5 t6)
	(le t6 t6)
	(next t0 t1)
	(next t1 t2)
	(next t2 t3)
	(next t3 t4)
	(next t4 t5)
	(next t5 t6)
	(loc-x l1 c4)
	(loc-y l1 c13)
	(loc-x l2 c6)
	(loc-y l2 c36)
	(loc-x l3 c25)
	(loc-y l3 c11)
	(road-distance l1 l2 d23)
	(road-speed l1 l2 s50)
	(zero-time-road l1 l2)
	(road-distance l1 l3 d21)
	(road-speed l1 l3 s65)
	(zero-time-road l1 l3)
	(road-distance l2 l1 d23)
	(road-speed l2 l1 s50)
	(zero-time-road l2 l1)
	(road-distance l2 l3 d31)
	(road-speed l2 l3 s40)
	(road-span l2 l3 t0 t1)
	(road-span l2 l3 t1 t2)
	(road-span l2 l3 t2 t3)
	(road-span l2 l3 t3 t4)
	(road-span l2 l3 t4 t5)
	(road-span l2 l3 t5 t6)
	(road-distance l3 l1 d21)
	(road-speed l3 l1 s65)
	(zero-time-road l3 l1)
	(road-distance l3 l2 d31)
	(road-speed l3 l2 s40)
	(road-span l3 l2 t0 t1)
	(road-span l3 l2 t1 t2)
	(road-span l3 l2 t2 t3)
	(road-span l3 l2 t3 t4)
	(road-span l3 l2 t4 t5)
	(road-span l3 l2 t5 t6)
)

(:goal (and 
	(delivered package1 l3 t3)
	(at-destination package2 l1)
	(delivered package3 l1 t6)
))

)
