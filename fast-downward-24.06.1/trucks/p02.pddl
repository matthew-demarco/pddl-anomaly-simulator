(define (problem truck-2)
(:domain Trucks)

(:objects
	truck1 - truck
	package1 - package
	package2 - package
	package3 - package
	package4 - package
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
	d18 - mile
	d25 - mile
	d38 - mile
	s30 - mph
	s40 - mph
	s50 - mph
	c9 - gridcoord
	c10 - gridcoord
	c15 - gridcoord
	c27 - gridcoord
	c34 - gridcoord
	c39 - gridcoord
)

(:init
	(at truck1 l2)
	(free a1 truck1)
	(free a2 truck1)
	(closer a1 a2)
	(at package1 l1)
	(at package2 l1)
	(at package3 l1)
	(at package4 l1)
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
	(loc-x l1 c34)
	(loc-y l1 c39)
	(loc-x l2 c27)
	(loc-y l2 c15)
	(loc-x l3 c10)
	(loc-y l3 c9)
	(road-distance l1 l2 d25)
	(road-speed l1 l2 s40)
	(road-span l1 l2 t0 t1)
	(road-span l1 l2 t1 t2)
	(road-span l1 l2 t2 t3)
	(road-span l1 l2 t3 t4)
	(road-span l1 l2 t4 t5)
	(road-span l1 l2 t5 t6)
	(road-distance l1 l3 d38)
	(road-speed l1 l3 s50)
	(road-span l1 l3 t0 t1)
	(road-span l1 l3 t1 t2)
	(road-span l1 l3 t2 t3)
	(road-span l1 l3 t3 t4)
	(road-span l1 l3 t4 t5)
	(road-span l1 l3 t5 t6)
	(road-distance l2 l1 d25)
	(road-speed l2 l1 s40)
	(road-span l2 l1 t0 t1)
	(road-span l2 l1 t1 t2)
	(road-span l2 l1 t2 t3)
	(road-span l2 l1 t3 t4)
	(road-span l2 l1 t4 t5)
	(road-span l2 l1 t5 t6)
	(road-distance l2 l3 d18)
	(road-speed l2 l3 s30)
	(road-span l2 l3 t0 t1)
	(road-span l2 l3 t1 t2)
	(road-span l2 l3 t2 t3)
	(road-span l2 l3 t3 t4)
	(road-span l2 l3 t4 t5)
	(road-span l2 l3 t5 t6)
	(road-distance l3 l1 d38)
	(road-speed l3 l1 s50)
	(road-span l3 l1 t0 t1)
	(road-span l3 l1 t1 t2)
	(road-span l3 l1 t2 t3)
	(road-span l3 l1 t3 t4)
	(road-span l3 l1 t4 t5)
	(road-span l3 l1 t5 t6)
	(road-distance l3 l2 d18)
	(road-speed l3 l2 s30)
	(road-span l3 l2 t0 t1)
	(road-span l3 l2 t1 t2)
	(road-span l3 l2 t2 t3)
	(road-span l3 l2 t3 t4)
	(road-span l3 l2 t4 t5)
	(road-span l3 l2 t5 t6)
)

(:goal (and 
	(delivered package1 l2 t3)
	(delivered package2 l2 t3)
	(at-destination package3 l2)
	(delivered package4 l3 t6)
))

)
